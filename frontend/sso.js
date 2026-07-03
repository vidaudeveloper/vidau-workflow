/** VidAU SSO 前端辅助 — 登录页与主站共用 */
window.VidauSsoHelper = {
  _sessionInflight: null,

  loadSdk(sdkUrl) {
    return new Promise((resolve, reject) => {
      if (window.VidauSSO) {
        resolve(window.VidauSSO);
        return;
      }
      if (!sdkUrl) {
        reject(new Error("未配置 SSO SDK 地址"));
        return;
      }
      const existing = document.querySelector('script[data-vidau-sso="1"]');
      if (existing) {
        existing.addEventListener("load", () => resolve(window.VidauSSO));
        existing.addEventListener("error", () => reject(new Error("SSO SDK 加载失败")));
        return;
      }
      const script = document.createElement("script");
      script.src = sdkUrl;
      script.async = true;
      script.dataset.vidauSso = "1";
      script.onload = () => {
        if (window.VidauSSO) resolve(window.VidauSSO);
        else reject(new Error("SSO SDK 未暴露 VidauSSO"));
      };
      script.onerror = () => reject(new Error("SSO SDK 加载失败"));
      document.head.appendChild(script);
    });
  },

  async establishSession(token) {
    const raw = (token || "").trim();
    if (!raw) throw new Error("缺少 token");
    if (this._sessionInflight?.token === raw) {
      return this._sessionInflight.promise;
    }
    const promise = (async () => {
      const res = await fetch("/api/auth/sso/callback", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: raw }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || data.msg || "SSO 会话建立失败");
      }
      return data;
    })();
    this._sessionInflight = { token: raw, promise };
    try {
      return await promise;
    } finally {
      if (this._sessionInflight?.token === raw) {
        this._sessionInflight = null;
      }
    }
  },

  async ensureInit(ssoConfig, hooks = {}) {
    const SSO = await this.loadSdk(ssoConfig.sdk_url);
    if (!window.__vidauSsoInited) {
      SSO.init({
        appId: ssoConfig.app_id,
        env: ssoConfig.env || undefined,
        debug: ssoConfig.env === "development",
        onLoginSuccess: hooks.onLoginSuccess,
        onLogout: hooks.onLogout,
        onAuthChange: hooks.onAuthChange,
      });
      window.__vidauSsoInited = true;
    }
    return SSO;
  },

  async tryExistingSession(ssoConfig) {
    const SSO = await this.ensureInit(ssoConfig);
    if (!SSO.isLoggedIn() || !SSO.getToken()) return null;
    await this.establishSession(SSO.getToken());
    return { user: SSO.getUser(), token: SSO.getToken() };
  },

  /** 弹出 SSO 登录窗；登录成功后 resolve，用户关闭弹窗未登录则 reject */
  promptLogin(ssoConfig) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (fn, value) => {
        if (settled) return;
        settled = true;
        fn(value);
      };
      const handleToken = async (token) => {
        try {
          await this.establishSession(token);
          finish(resolve, token);
        } catch (err) {
          finish(reject, err);
        }
      };
      this.ensureInit(ssoConfig, {
        onLoginSuccess: (_user, token) => handleToken(token),
      })
        .then((SSO) => {
          if (SSO.isLoggedIn() && SSO.getToken()) {
            return handleToken(SSO.getToken());
          }
          SSO.login();
        })
        .catch((err) => finish(reject, err));
    });
  },

  async logout(ssoConfig) {
    if (!ssoConfig?.enabled || !ssoConfig.sdk_url) return;
    try {
      const SSO = await this.ensureInit(ssoConfig);
      SSO.logout();
    } catch {
      /* ignore */
    }
  },
};
