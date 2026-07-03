// VidAU 素材工作流 — Jenkins 部署
//
// 分支约定（与运维统一）：
//   test  → 测试环境（vidau.info / 测试机）
//   main  → 正式环境（vidau.ai / 生产机）
//
// 运维一次性配置：
//   1. Jenkins → Credentials → SSH 私钥（vidau-workflow-deploy-ssh）
//   2. 建议建两个 Job（或同一 Job 改参数）：
//      - 测试：GIT_BRANCH=test，DEPLOY_HOST=测试机 IP
//      - 生产：GIT_BRANCH=main，DEPLOY_HOST=生产机 IP
//   3. Script Path: Jenkinsfile
//
// 日常：merge 到 test → 部署测试；验证后 merge test → main → 部署生产

pipeline {
    agent any

    options {
        timeout(time: 20, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }

    parameters {
        choice(
            name: 'DEPLOY_MODE',
            choices: ['update', 'full'],
            description: 'update=拉代码+重启（日常）；full=首次/重装（跑 deploy_server.sh）'
        )
        string(
            name: 'DEPLOY_HOST',
            defaultValue: '35.187.225.132',
            description: '生产服务器 IP 或主机名'
        )
        string(
            name: 'DEPLOY_USER',
            defaultValue: 'root',
            description: 'SSH 登录用户'
        )
        string(
            name: 'APP_DIR',
            defaultValue: '/opt/vidau-workflow',
            description: '服务器上的项目目录'
        )
        string(
            name: 'GIT_BRANCH',
            defaultValue: 'main',
            description: '要部署的 Git 分支'
        )
        string(
            name: 'SSH_CREDENTIALS_ID',
            defaultValue: 'vidau-workflow-deploy-ssh',
            description: 'Jenkins 里配置的 SSH 私钥 Credential ID'
        )
    }

    stages {
        stage('Deploy') {
            steps {
                sshagent(credentials: [params.SSH_CREDENTIALS_ID]) {
                    script {
                        def remote = "${params.DEPLOY_USER}@${params.DEPLOY_HOST}"
                        def appDir = params.APP_DIR
                        def branch = params.GIT_BRANCH
                        echo "Deploy branch=${branch} to ${remote}"

                        if (params.DEPLOY_MODE == 'full') {
                            sh """
                                ssh -o StrictHostKeyChecking=accept-new ${remote} \\
                                    'APP_DIR=${appDir} REPO_URL=https://gt.superads.cn/vidau/vidau-workflow.git bash -s' \\
                                    < scripts/deploy_server.sh
                            """
                        } else {
                            sh """
                                ssh -o StrictHostKeyChecking=accept-new ${remote} \\
                                    'APP_DIR=${appDir} GIT_BRANCH=${branch} bash -s' \\
                                    < scripts/jenkins_update.sh
                            """
                        }
                    }
                }
            }
        }

        stage('Verify public URL') {
            steps {
                sh '''
                    curl -fsS -m 15 https://adflow.vidau.ai/health || \\
                    curl -fsS -m 15 https://adflow.vidau.ai/api/meta | head -c 200
                    echo ""
                '''
            }
        }
    }

    post {
        success {
            echo '部署成功。正式 https://adflow.vidau.ai · 测试 https://adflow.vidau.info'
        }
        failure {
            echo '部署失败。请在服务器执行: sudo journalctl -u bluetti-workflow -n 80 --no-pager'
        }
    }
}
