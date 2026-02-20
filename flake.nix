{
  description = "ClimatIQ - Intelligent Heat Pump Control with ML";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        
        pythonEnv = pkgs.python311.withPackages (ps: with ps; [
          # Core dependencies
          influxdb
          scikit-learn
          numpy
          pandas
          pydantic
          
          # Development tools
          pytest
          pytest-cov
          black
          mypy
        ]);
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            pythonEnv
            pkgs.ruff
            pkgs.git
            pkgs.curl
            pkgs.jq
          ];
          
          shellHook = ''
            echo ""
            echo "🌡️  ClimatIQ Development Environment"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "Python: $(python --version)"
            echo ""
            echo "📦 Available packages:"
            echo "   • influxdb, scikit-learn, numpy, pandas, pydantic"
            echo ""
            echo "🛠️  Development tools:"
            echo "   • black (formatter)"
            echo "   • ruff (linter)"
            echo "   • pytest (testing)"
            echo "   • mypy (type checking)"
            echo ""
            echo "💡 Quick start:"
            echo "   pytest                    # Run tests"
            echo "   black . && ruff check .   # Format & lint"
            echo ""
          '';
        };
      }
    );
}
