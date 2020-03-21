pipeline {
  agent {
    label 'docker'
  }
  options {
    ansiColor('xterm')
  }
  environment {
    PACKAGE  = 'kframework'
    VERSION  = '5.0.0'
    ROOT_URL = 'https://github.com/kframework/k/releases/download'
    MAKE_EXTRA_ARGS = '' // Example: 'DEBUG=--debug' to see stack traces
  }
  stages {
    stage("Init title") {
      when { changeRequest() }
      steps {
        script {
          currentBuild.displayName = "PR ${env.CHANGE_ID}: ${env.CHANGE_TITLE}"
        }
      }
    }
    stage("Create source tarball") {
      agent {
        dockerfile {
          filename 'Dockerfile.debian'
          additionalBuildArgs '--build-arg USER_ID=$(id -u) --build-arg GROUP_ID=$(id -g) --build-arg BASE_IMAGE=ubuntu:bionic'
          reuseNode true
        }
      }
      steps {
        dir("kframework-${env.VERSION}") {
          checkout scm
          sh '''
            find . -name .git | xargs rm -r
            cd ..
            tar czvf kframework-${VERSION}-src.tar.gz kframework-${VERSION}
          '''
          deleteDir()
        }
        stash name: "src", includes: "kframework-${env.VERSION}-src.tar.gz"
      }
    }
    stage('Update Submodules (non-release)') {
      when { branch 'master' }
      steps {
        build job: 'rv-devops/master', propagate: false, wait: false                                   \
            , parameters: [ booleanParam(name: 'UPDATE_DEPS_SUBMODULE', value: true)                   \
                          , string(name: 'PR_REVIEWER', value: 'ehildenb')                             \
                          , string(name: 'UPDATE_DEPS_REPOSITORY', value: 'kframework/wasm-semantics') \
                          , string(name: 'UPDATE_DEPS_SUBMODULE_DIR', value: 'deps/k')                 \
                          ]
        build job: 'rv-devops/master', propagate: false, wait: false                                               \
            , parameters: [ booleanParam(name: 'UPDATE_DEPS_SUBMODULE', value: true)                               \
                          , string(name: 'PR_REVIEWER', value: 'malturki')                                         \
                          , string(name: 'UPDATE_DEPS_REPOSITORY', value: 'runtimeverification/beacon-chain-spec') \
                          , string(name: 'UPDATE_DEPS_SUBMODULE_DIR', value: 'deps/k')                             \
                          ]
        build job: 'rv-devops/master', propagate: false, wait: false                                          \
            , parameters: [ booleanParam(name: 'UPDATE_DEPS_SUBMODULE', value: true)                          \
                          , string(name: 'PR_REVIEWER', value: 'ehildenb')                                    \
                          , string(name: 'UPDATE_DEPS_REPOSITORY', value: 'runtimeverification/mkr-mcd-spec') \
                          , string(name: 'UPDATE_DEPS_SUBMODULE_DIR', value: 'deps/k')                        \
                          ]
        build job: 'rv-devops/master', propagate: false, wait: false                                                       \
            , parameters: [ booleanParam(name: 'UPDATE_DEPS_SUBMODULE', value: true)                                       \
                          , string(name: 'PR_REVIEWER', value: 'daejunpark')                                               \
                          , string(name: 'UPDATE_DEPS_REPOSITORY', value: 'runtimeverification/beacon-chain-verification') \
                          , string(name: 'UPDATE_DEPS_SUBMODULE_DIR', value: 'deps/k')                                     \
                          ]
      }
    }
    stage('Build and Package K') {
      failFast true
      parallel {
        stage('Build and Package K on Linux') {
          stages {
            stage('Build and Package on Ubuntu Bionic') {
              stages {
                stage('Build on Ubuntu Bionic') {
                  agent {
                    dockerfile {
                      filename 'Dockerfile.debian'
                      additionalBuildArgs '--build-arg USER_ID=$(id -u) --build-arg GROUP_ID=$(id -g) --build-arg BASE_IMAGE=ubuntu:bionic'
                      reuseNode true
                    }
                  }
                  stages {
                    stage('Checkout code') {
                      steps {
                        dir('k-exercises') {
                          git url: 'git@github.com:kframework/k-exercises.git'
                        }
                      }
                    }
                    stage('Build and Test K') {
                      steps {
                        sh '''
                          echo 'Setting up environment...'
                          eval `opam config env`
                          echo 'Building K...'
                          mvn --batch-mode verify -U
                          echo 'Starting kserver...'
                          export K_OPTS="-Xmx8G"
                          k-distribution/target/release/k/bin/spawn-kserver kserver.log
                          cd k-exercises/tutorial
                          make -j`nproc` ${MAKE_EXTRA_ARGS}
                        '''
                      }
                    }
                    stage('Build Debian Package') {
                      steps {
                        dir("kframework-${env.VERSION}") {
                          checkout scm
                          sh '''
                            mv debian/control.ubuntu debian/control
                            dpkg-buildpackage
                          '''
                        }
                        stash name: "bionic", includes: "kframework_${env.VERSION}_amd64.deb"
                      }
                    }
                  }
                  post {
                    always {
                      sh 'k-distribution/target/release/k/bin/stop-kserver || true'
                      archiveArtifacts 'kserver.log,k-distribution/target/kserver.log'
                    }
                  }
                }
                stage('Test Debian Package') {
                  agent {
                    docker {
                      image 'ubuntu:bionic'
                      args '-u 0'
                      reuseNode true
                    }
                  }
                  options { skipDefaultCheckout() }
                  steps {
                    unstash "bionic"
                    sh 'src/main/scripts/test-in-container-debian'
                  }
                  post {
                    always {
                      sh 'stop-kserver || true'
                      archiveArtifacts 'kserver.log,k-distribution/target/kserver.log'
                    }
                  }
                }
              }
            }
            stage('Build and Package on Debian Buster') {
              when { branch 'master' }
              stages {
                stage('Build on Debian Buster') {
                  agent {
                    dockerfile {
                      filename 'Dockerfile.debian'
                      additionalBuildArgs '--build-arg USER_ID=$(id -u) --build-arg GROUP_ID=$(id -g) --build-arg BASE_IMAGE=debian:buster --build-arg LLVM_VERSION=7'
                      reuseNode true
                    }
                  }
                  stages {
                    stage('Build Debian Package') {
                      steps {
                        dir("kframework-${env.VERSION}") {
                          checkout scm
                          sh '''
                            mv debian/control.debian debian/control
                            dpkg-buildpackage
                          '''
                        }
                        stash name: "buster", includes: "kframework_${env.VERSION}_amd64.deb"
                      }
                    }
                  }
                }
                stage('Test Debian Package') {
                  agent {
                    docker {
                      image 'debian:buster'
                      args '-u 0'
                      reuseNode true
                    }
                  }
                  options { skipDefaultCheckout() }
                  steps {
                    unstash "buster"
                    sh '''
                      src/main/scripts/test-in-container-debian
                    '''
                  }
                  post {
                    always {
                      sh 'stop-kserver || true'
                      archiveArtifacts 'kserver.log,k-distribution/target/kserver.log'
                    }
                  }
                }
              }
              post {
                failure {
                  slackSend color: '#cb2431'                                             \
                          , channel: '#k'                                                \
                          , message: "Debian Buster Packaging Failed: ${env.BUILD_URL}"
                }
              }
            }
            stage('Build and Package on Arch Linux') {
              when { branch 'master' }
              stages {
                stage('Build on Arch Linux') {
                  agent {
                    dockerfile {
                      filename 'Dockerfile.arch'
                      additionalBuildArgs '--build-arg USER_ID=$(id -u) --build-arg GROUP_ID=$(id -g)'
                      reuseNode true
                    }
                  }
                  stages {
                    stage('Build Pacman Package') {
                      steps {
                        checkout scm
                        sh '''
                          makepkg
                        '''
                        stash name: "arch", includes: "kframework-git-${env.VERSION}-1-x86_64.pkg.tar.xz"
                      }
                    }
                  }
                }
                stage('Test Arch Package') {
                  agent {
                    docker {
                      image 'archlinux/base'
                      args '-u 0'
                      reuseNode true
                    }
                  }
                  options { skipDefaultCheckout() }
                  steps {
                    unstash "arch"
                    sh '''
                      pacman -Syyu --noconfirm
                      pacman -U --noconfirm kframework-git-${VERSION}-1-x86_64.pkg.tar.xz
                      src/main/scripts/test-in-container
                    '''
                  }
                  post {
                    always {
                      sh 'stop-kserver || true'
                      archiveArtifacts 'kserver.log,k-distribution/target/kserver.log'
                    }
                  }
                }
              }
              post {
                failure {
                  slackSend color: '#cb2431'                                         \
                          , channel: '#k'                                            \
                          , message: "Arch Linux Packaging Failed: ${env.BUILD_URL}"
                }
              }
            }
            stage('Build Platform Independent K Binary') {
              when { branch 'master' }
              agent {
                dockerfile {
                  filename 'Dockerfile.debian'
                  additionalBuildArgs '--build-arg USER_ID=$(id -u) --build-arg GROUP_ID=$(id -g) --build-arg BASE_IMAGE=ubuntu:bionic'
                  reuseNode true
                }
              }
              steps {
                sh '''
                  eval `opam config env`
                  mvn --batch-mode clean
                  mvn --batch-mode install -DskipKTest -Dcheckstyle.skip
                  mv k-distribution/target/k-nightly.tar.gz ./
                '''
                stash name: "binary", includes: "k-nightly.tar.gz"
              }
              post {
                failure {
                  slackSend color: '#cb2431'                                                  \
                          , channel: '#k'                                                     \
                          , message: "Platform Independent K Binary Failed: ${env.BUILD_URL}"
                }
              }
            }
          }
        }
        stage('Build and Package on Mac OS') {
          when { branch 'master' }
          stages {
            stage('Build on Mac OS') {
              stages {
                stage('Build Homebrew Bottle') {
                  agent {
                    label 'anka'
                  }
                  steps {
                    unstash "src"
                    dir('homebrew-k') {
                      git url: 'git@github.com:kframework/homebrew-k.git'
                      sh '''
                        git config --global user.email "admin@runtimeverification.com"
                        git config --global user.name  "RV Jenkins"
                        ${WORKSPACE}/src/main/scripts/brew-build-bottle
                      '''
                      stash name: "mojave", includes: "kframework--${env.VERSION}.mojave.bottle*.tar.gz"
                    }
                  }
                }
                stage("Test Homebrew Bottle") {
                  agent {
                    label 'anka'
                  }
                  steps {
                    dir('homebrew-k') {
                      git url: 'git@github.com:kframework/homebrew-k.git', branch: 'brew-release-kframework'
                      unstash "mojave"
                      sh '''
                        ${WORKSPACE}/src/main/scripts/brew-install-bottle
                      '''
                    }
                    sh '''
                      cp -R /usr/local/lib/kframework/tutorial ~
                      WD=`pwd`
                      cd
                      echo 'Starting kserver...'
                      /usr/local/lib/kframework/bin/spawn-kserver $WD/kserver.log
                      cd tutorial
                      echo 'Testing tutorial in user environment...'
                      make -j`sysctl -n hw.ncpu` ${MAKE_EXTRA_ARGS}
                      cd ~
                      echo "module TEST imports BOOL endmodule" > test.k
                      kompile test.k --backend llvm
                      kompile test.k --backend haskell
                    '''
                    dir('homebrew-k') {
                      sh '''
                        ${WORKSPACE}/src/main/scripts/brew-update-to-final
                      '''
                    }
                  }
                  post {
                    always {
                      sh 'stop-kserver || true'
                      archiveArtifacts 'kserver.log,k-distribution/target/kserver.log'
                    }
                  }
                }
              }
              post {
                always {
                  archiveArtifacts artifacts: 'kserver.log,k-distribution/target/kserver.log', allowEmptyArchive: true
                }
              }
            }
          }
          post {
            failure {
              slackSend color: '#cb2431'                                    \
                      , channel: '#k'                                       \
                      , message: "MacOS Packaging Failed: ${env.BUILD_URL}"
            }
          }
        }
      }
    }
    stage('Deploy') {
      agent {
        dockerfile {
          filename 'Dockerfile.arch'
          additionalBuildArgs '--build-arg USER_ID=$(id -u) --build-arg GROUP_ID=$(id -g)'
          reuseNode true
        }
      }
      when {
        branch 'master'
        beforeAgent true
      }
      environment {
        AWS_ACCESS_KEY_ID     = credentials('aws-access-key-id')
        AWS_SECRET_ACCESS_KEY = credentials('aws-secret-access-key')
        AWS_REGION            = 'us-east-2'
        GITHUB_TOKEN          = credentials('rv-jenkins')
        GIT_SSH_COMMAND       = 'ssh -o StrictHostKeyChecking=accept-new'
      }
      steps {
        unstash "src"
        unstash "binary"
        dir("bionic") {
          unstash "bionic"
        }
        dir("buster") {
          unstash "buster"
        }
        dir("arch") {
          unstash "arch"
        }
        dir("mojave") {
          unstash "mojave"
        }
        sshagent(['2b3d8d6b-0855-4b59-864a-6b3ddf9c9d1a']) {
          sh '''
            release_tag="v${VERSION}-$(git rev-parse --short=7 HEAD)"
            mv bionic/kframework_${VERSION}_amd64.deb bionic/kframework_${VERSION}_amd64_bionic.deb
            mv buster/kframework_${VERSION}_amd64.deb buster/kframework_${VERSION}_amd64_buster.deb
            LOCAL_BOTTLE_NAME=$(echo mojave/kframework--${VERSION}.mojave.bottle*.tar.gz)
            BOTTLE_NAME=`cd mojave && echo kframework--${VERSION}.mojave.bottle*.tar.gz | sed 's!kframework--!kframework-!'`
            mv $LOCAL_BOTTLE_NAME mojave/$BOTTLE_NAME
            echo "K Framework Release $release_tag"  > release.md
            echo ""                                 >> release.md
            cat k-distribution/INSTALL.md           >> release.md
            hub release create                                                                         \
                --attach kframework-${VERSION}-src.tar.gz"#Source tar.gz"                              \
                --attach bionic/kframework_${VERSION}_amd64_bionic.deb"#Ubuntu Bionic (18.04) Package" \
                --attach buster/kframework_${VERSION}_amd64_buster.deb"#Debian Buster (10) Package"    \
                --attach arch/kframework-git-${VERSION}-1-x86_64.pkg.tar.xz"#Arch Package"             \
                --attach mojave/$BOTTLE_NAME"#Mac OS X Homebrew Bottle"                                \
                --attach k-nightly.tar.gz"#Platform Indepdendent K Binary"                             \
                --file release.md "${release_tag}"
          '''
        }
        dir("homebrew-k") {
          git url: 'git@github.com:kframework/homebrew-k.git', branch: 'brew-release-kframework'
          sshagent(['2b3d8d6b-0855-4b59-864a-6b3ddf9c9d1a']) {
            sh '''
              git config --global user.email "admin@runtimeverification.com"
              git config --global user.name  "RV Jenkins"
              git checkout master
              git merge brew-release-$PACKAGE
              git push origin master
              git push origin -d brew-release-$PACKAGE
            '''
          }
        }
      }
      post {
        failure {
          slackSend color: '#cb2431'                                 \
                  , channel: '#k'                                    \
                  , message: "Deploy Phase Failed: ${env.BUILD_URL}"
        }
      }
    }
    stage('Update Submodules (release)') {
      when { branch 'master' }
      steps {
        build job: 'rv-devops/master', propagate: false, wait: false                                  \
            , parameters: [ booleanParam(name: 'UPDATE_DEPS_SUBMODULE', value: true)                  \
                          , string(name: 'PR_REVIEWER', value: 'ehildenb')                            \
                          , string(name: 'UPDATE_DEPS_REPOSITORY', value: 'kframework/evm-semantics') \
                          , string(name: 'UPDATE_DEPS_SUBMODULE_DIR', value: 'deps/k')                \
                          ]
        build job: 'rv-devops/master', propagate: false, wait: false                          \
            , parameters: [ booleanParam(name: 'UPDATE_DEPS_RELEASE_URL', value: true)        \
                          , string(name: 'PR_REVIEWER', value: 'ttuegel')                     \
                          , string(name: 'UPDATE_DEPS_REPOSITORY', value: 'kframework/kore')  \
                          , string(name: 'UPDATE_DEPS_RELEASE_FILE', value: 'deps/k_release') \
                          ]
      }
    }
  }
}
