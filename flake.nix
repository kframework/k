{
  description = "K Framework";
  inputs = {
    rv-nix-tools.url = "github:runtimeverification/rv-nix-tools/854d4f05ea78547d46e807b414faad64cea10ae4";
    nixpkgs.follows = "rv-nix-tools/nixpkgs";

    llvm-backend.url = "github:runtimeverification/llvm-backend/v0.1.141";
    llvm-backend.inputs.nixpkgs.follows = "nixpkgs";

    haskell-backend = {
      url = "github:runtimeverification/haskell-backend/v0.1.155";
      inputs.rv-nix-tools.follows = "rv-nix-tools";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    flake-utils.follows = "llvm-backend/utils";

    uv2nix.url = "github:pyproject-nix/uv2nix/9d357f0d2ce6f5f35ec7959d7e704452352eb4da";
    # uv2nix requires a newer version of nixpkgs
    # therefore, we pin uv2nix specifically to a newer version of nixpkgs
    # until we replaced our stale version of nixpkgs with an upstream one as well
    # but also uv2nix requires us to call it with `callPackage`, so we add stuff
    # from the newer nixpkgs to our stale nixpkgs via an overlay
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixos-unstable";
    uv2nix.inputs.nixpkgs.follows = "nixpkgs-unstable";
    # uv2nix.inputs.nixpkgs.follows = "nixpkgs";
    pyproject-build-systems.url = "github:pyproject-nix/build-system-pkgs/042904167604c681a090c07eb6967b4dd4dae88c";
    pyproject-build-systems = {
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.uv2nix.follows = "uv2nix";
      inputs.pyproject-nix.follows = "uv2nix/pyproject-nix";
    };
    pyproject-nix.follows = "uv2nix/pyproject-nix";
  };

  outputs = { self, nixpkgs, flake-utils, rv-nix-tools, haskell-backend
    , llvm-backend, pyproject-nix, pyproject-build-systems, uv2nix, nixpkgs-unstable }:
    let
      # due to the nixpkgs that we use in this flake being outdated, uv is also heavily outdated
      # we can instead use the binary release of uv provided by uv2nix for now
      uvOverlay = final: prev: {
        uv = uv2nix.packages.${final.system}.uv-bin;
      };
      pykOverlay = final: prev: rec {
        pyk-pyproject = final.callPackage ./nix/pyk-pyproject {
          inherit uv2nix;
        };

        pyk-python310 = final.callPackage ./nix/pyk {
          inherit pyproject-nix pyproject-build-systems pyk-pyproject;
          python = final."python310";
        };
        pyk-python311 = final.callPackage ./nix/pyk {
          inherit pyproject-nix pyproject-build-systems pyk-pyproject;
          python = final."python311";
        };
        pyk = pyk-python310;
      };
      allOverlays = [
        (_: _: {
          llvm-version = 17;
          llvm-backend-build-type = "Release";
        })

        llvm-backend.overlays.default

        haskell-backend.overlays.z3
        haskell-backend.overlays.integration-tests

        uvOverlay
        pykOverlay

        (final: prev:
          let
            k-version =
              prev.lib.removeSuffix "\n" (builtins.readFile ./package/version);
            src = prev.stdenv.mkDerivation {
              name = "k-${k-version}-${self.rev or "dirty"}-src";
              src = prev.lib.cleanSource
                (prev.nix-gitignore.gitignoreSourcePure [
                  ./.gitignore
                  ".github/"
                  "result*"
                  "nix/"
                  "*.nix"
                  "haskell-backend/src/main/native/haskell-backend/*"
                  "llvm-backend/src/main/native/llvm-backend/*"
                  "k-distribution/tests/regression-new"
                  # do not include submodule directories that might be initilized empty or non-existent
                  "/web/k-web-theme"
                ] ./.);
              dontBuild = true;
              installPhase = ''
                mkdir $out
                cp -rv $src/* $out
                chmod -R u+w $out
                mkdir -p $out/llvm-backend/src/main/native/llvm-backend/matching
                cp -rv ${llvm-backend}/matching/* $out/llvm-backend/src/main/native/llvm-backend/matching
              '';
            };
          in {
            # this version of maven from nixpkgs 23.11. we can remove this version of maven once our nixpkgs catches up
            maven = prev.callPackage ./nix/maven.nix { };

            haskell-backend-bins = prev.symlinkJoin {
              name = "kore-${haskell-backend.sourceInfo.shortRev or "local"}";
              paths = let p = haskell-backend.packages.${prev.system};
              in [
                p.kore-exec
                p.kore-match-disjunction
                p.kore-parser
                p.kore-repl
                p.kore-rpc
                p.kore-rpc-booster
                p.kore-rpc-client
                p.booster-dev
              ];
            };

            mk-k-framework = { haskell-backend-bins, llvm-kompile-libs }:
              prev.callPackage ./nix/k.nix {
                mvnHash = "sha256-Hn+MfNow6H42ZUShNiJnZsZhlV5AkxlsYUaewxnaN1w=";
                manualMvnArtifacts = [
                  "org.scala-lang:scala-compiler:2.13.13"
                  "ant-contrib:ant-contrib:1.0b3"
                  "org.apache.ant:ant-nodeps:1.8.1"
                  "org.apache.maven.wagon:wagon-provider-api:1.0-alpha-6"
                  "org.checkerframework:checker-qual:3.33.0"
                  "com.google.errorprone:error_prone_annotations:2.18.0"
                  "se.vandmo:dependency-lock-maven-plugin:1.2.2"
                ];
                manualMvnArtifactsJars = [
                  # e.g., this is basically se.vandmo:dependency-lock-maven-plugin:1.2.2:jar, but this way it works with `mvn dependency:get`
                  "se.vandmo:dependency-lock-maven-plugin:1.2.2"
                  "com.runtimeverification.k:k-frontend:1.0-SNAPSHOT"
                  "com.runtimeverification.k:llvm-backend-matching:1.0-SNAPSHOT"
                  "com.runtimeverification.k:llvm-backend:1.0-SNAPSHOT"
                  "com.runtimeverification.k:haskell-backend:1.0-SNAPSHOT"
                ];
                manualMvnSourceArtifacts =
                  [ "org.scala-sbt:compiler-bridge_2.13:1.8.0" ];
                fileReplacements = [
                  {
                    replace = "com/google/code/gson/gson/maven-metadata-central.xml";
                    replaceWith = ./nix/resources/maven-metadata-central-replacements/GSON.xml;
                    sha1 = "6761f9978777a91d499185a1516ea120f8f80a22";
                  }
                ];
                inherit (final) maven;
                inherit (prev) llvm-backend;
                clang = prev."clang_${toString final.llvm-version}";
                haskell-backend = haskell-backend-bins;
                inherit (haskell-backend) prelude-kore;
                inherit src;
                debugger = if prev.stdenv.isDarwin then
                # lldb is broken on this version of nixpkgs-unstable and there is no point including it
                # before the lldb support for k is added: https://github.com/runtimeverification/k/issues/2650
                  null
                else
                  prev.gdb;
                version = "${k-version}-${self.rev or "dirty"}";
                inherit llvm-kompile-libs;
              };

            k = final.mk-k-framework {
              inherit (final) haskell-backend-bins;
              llvm-kompile-libs = with prev; {
                procps = [ "-I${procps}/include" "-L${procps}/lib" ];
                openssl = [ "-I${openssl.dev}/include" "-L${openssl.out}/lib" ];
                secp256k1 = [ "-I${secp256k1}/include" "-L${secp256k1}/lib" ];
              };
            };

            k-lock = final.k.overrideAttrs (finalAttrs: previousAttrs: {
              nativeBuildInputs = previousAttrs.nativeBuildInputs ++ (with final; [
                rsync
              ]);
              buildPhase = previousAttrs.buildPhase + ''
                echo "now running lock plugin offline"
                mvn -o -Dmaven.repo.local=.m2 se.vandmo:dependency-lock-maven-plugin:1.2.2:lock
              '';
              installPhase = previousAttrs.installPhase + ''
                mkdir -p $out/lock
                rsync -R dependencies-lock.json haskell-backend/dependencies-lock.json k-distribution/dependencies-lock.json k-frontend/dependencies-lock.json llvm-backend/dependencies-lock.json llvm-backend/src/main/native/llvm-backend/matching/dependencies-lock.json $out/lock/
              '';
            });
          })
      ];
    in flake-utils.lib.eachSystem [
      "x86_64-linux"
      "x86_64-darwin"
      "aarch64-linux"
      "aarch64-darwin"
    ] (system:
      let
        pkgs-unstable = import nixpkgs-unstable {
          inherit system;
        };
        # for uv2nix, remove this once we updated to a newer version of nixpkgs
        staleNixpkgsOverlay = final: prev: {
          inherit (pkgs-unstable) replaceVars;
        };
        pkgs = nixpkgs.lib.trivial.warnIf (llvm-backend.inputs.nixpkgs.rev
          != haskell-backend.inputs.nixpkgs.rev)
          "The version of nixpkgs in Haskell backend and LLVM backend has diverged!"
          import nixpkgs {
            inherit system;
            # Temporarily required until a bug on pyOpenSSL is resolved for aarch64-darwin
            # https://github.com/NixOS/nixpkgs/pull/172397
            config.allowBroken = system == "aarch64-darwin";
            overlays =
              [ (final: prev: { llvm-backend-build-type = "FastBuild"; }) ]
              ++ allOverlays
              ++ [
                staleNixpkgsOverlay
              ];
          };

      in rec {
        k-version =
          pkgs.lib.removeSuffix "\n" (builtins.readFile ./package/version);

        packages = rec {
          inherit (pkgs) k k-lock pyk pyk-python310 pyk-python311 pyk-pyproject maven;

          check-submodules = rv-nix-tools.lib.check-submodules pkgs {
            inherit llvm-backend haskell-backend;
          };

          smoke-test = with pkgs;
            stdenv.mkDerivation {
              name = "k-${k-version}-${self.rev or "dirty"}-smoke-test";
              src = lib.cleanSource
                (nix-gitignore.gitignoreSourcePure [ ./.gitignore ]
                  ./k-distribution);
              preferLocalBuild = true;
              buildInputs = [ lsof fmt gmp mpfr k ];
              buildFlags = [
                "K_BIN=${k}/bin"
                "KLLVMLIB=${k}/lib/kllvm"
                "PACKAGE_VERSION=${k-version}"
                "--output-sync"
              ];
              enableParallelBuilding = true;
              preBuild = ''
                cd tests/smoke
              '';
              installPhase = ''
                runHook preInstall
                touch "$out"
                runHook postInstall
              '';
            };

          test = with pkgs;
            stdenv.mkDerivation {
              name = "k-${k-version}-${self.rev or "dirty"}-test";
              src = lib.cleanSource
                (nix-gitignore.gitignoreSourcePure [ ./.gitignore ]
                  ./k-distribution);
              preferLocalBuild = true;
              buildInputs = [ fmt gmp mpfr k ];
              postPatch = ''
                patchShebangs tests/regression-new/*
                substituteInPlace tests/regression-new/append/kparse-twice \
                  --replace '"$(dirname "$0")/../../../bin/kparse"' '"${k}/bin/kparse"'
              '';

              buildFlags = [
                "K_BIN=${k}/bin"
                "KLLVMLIB=${k}/lib/kllvm"
                "PACKAGE_VERSION=${k-version}"
                "--output-sync"
              ];
              enableParallelBuilding = true;
              preBuild = ''
                cd tests/regression-new
              '';
              installPhase = ''
                runHook preInstall
                touch "$out"
                runHook postInstall
              '';
            };
        };
        defaultPackage = packages.k;
        devShells.kore-integration-tests = pkgs.kore-tests
          (pkgs.mk-k-framework {
            inherit (pkgs) haskell-backend-bins;
            llvm-kompile-libs = { };
          });
        devShells.uv = pkgs.mkShell {
          name = "uv develop shell";
          buildInputs = with pkgs; [
            python310
            uv
          ];
          env = {
            # prevent uv from managing Python downloads and force use of specific 
            UV_PYTHON_DOWNLOADS = "never";
            UV_PYTHON = pkgs.python310.interpreter;
          };
          shellHook = ''
            unset PYTHONPATH
          '';
        };
      }) // {
        overlays.llvm-backend = llvm-backend.overlays.default;
        overlays.z3 = haskell-backend.overlays.z3;
        overlays.pyk = final: prev: {
          inherit (self.packages.${final.system}) pyk pyk-python310 pyk-python311;
        };
        overlays.default = final: prev: {
          inherit (self.packages.${final.system}) k;
        };
        # this pyproject-nix overlay allows for overriding the python packages that are otherwise locked in `uv.lock`
        # by using this overlay in dependant nix flakes, you ensure that nix overrides also override the python package         
        overlays.pyk-pyproject = system: final: prev: {
          inherit (self.packages.${system}.pyk-pyproject.lockFileOverlay final prev) kframework;
        };

        # deprecated flake overlay output, please use `overlays.default` or `overlays.pyk` instead
        overlay = nixpkgs.lib.composeManyExtensions allOverlays;
      };
}
