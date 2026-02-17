{ lib
, fetchFromGitHub
, buildPythonPackage
, setuptools
}:

buildPythonPackage rec {
  pname = "sgtk";
  version = "0.0.0+git-62d128a";

  src = fetchFromGitHub {
    owner = "shotgunsoftware";
    repo = "tk-core";
    rev = "62d128a8a3e06fe37cc9de5c6a699415c6b51c70";
    hash = "sha256-gMA264hx7AOyjGUzkSlX2O7zFq5H6LAeGh68vMyUl2k=";
  };

  format = "setuptools";

  postPatch = ''
    substituteInPlace setup.py --replace 'return "dev"' 'return "0.0.0"'
  '';

  propagatedBuildInputs = [ setuptools ];

  doCheck = false;

  meta = with lib; {
    description = "Flow Production Tracking Toolkit Core API";
    homepage = "https://github.com/shotgunsoftware/tk-core";
    license = licenses.unfreeRedistributable;
    platforms = platforms.all;
  };
}
