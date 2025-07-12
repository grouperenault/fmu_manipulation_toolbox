import os
import re
from setuptools import setup

from fmu_manipulation_toolbox.version import __author__ as author, __version__ as default_version

try:
    version = os.environ["GITHUB_REF_NAME"]
except Exception as e:
    print(f"Cannot get repository status: {e}. Defaulting to {default_version}")
    version = default_version

if not re.match(r"[A-Za-z]?\d+(\.\d)+", version):
    print(f"WARNING: Version {version} does not match standard. The publication will fail !")
    version = default_version

# Create __version__.py
try:
    with open("fmu_manipulation_toolbox/__version__.py", "wt") as file:
        print(f"'{version}'", file=file)
except Exception as e:
    print(f"Cannot create __version__.py: {e}")

setup(
    name="fmu_manipulation_toolbox",
    version=version,
    packages=["fmu_manipulation_toolbox"],
    package_data={"fmu_manipulation_toolbox": [
        "resources/win32/client_sm.dll",
        "resources/win32/server_sm.exe",
        "resources/win64/client_sm.dll",
        "resources/win64/server_sm.exe",
        "resources/win64/container.dll",
        "resources/linux64/client_sm.so",
        "resources/linux64/server_sm",
        "resources/linux64/container.so",
        "resources/linux32/client_sm.so",
        "resources/linux32/server_sm",
        "resources/darwin64/container.dylib",
        "resources/license.txt",
        "resources/*.png",
        "resources/fmi-2.0/*.xsd",
        "resources/fmi-3.0/*.xsd",
    ]},
    entry_points={"console_scripts": ["fmutool = fmu_manipulation_toolbox.cli.fmutool:fmutool",
                                      "fmucontainer = fmu_manipulation_toolbox.cli.fmucontainer:fmucontainer",
                                      "fmusplit = fmu_manipulation_toolbox.cli.fmusplit:fmusplit"
                                      ],
                    "gui_scripts": ["fmutool-gui = fmu_manipulation_toolbox.gui:main"]
                  },
    author=author,
    url="https://github.com/grouperenault/fmu_manipulation_toolbox/",
    description="FMU Manipulation Toolbox is a python application for modifying Functional Mock-up Units "
                "(FMUs) without recompilation or bundling them into FMU Containers",
    long_description="""FMU Manipulation Toolbox is a python application for modifying Functional Mock-up Units (FMUs) 
without recompilation. It mainly modifies the `modelDescription.xml` file. It is highly customizable.

Manipulating the `modelDescription.xml` can be a dangerous thing! Communicating with the FMU-developer and adapting
the way the FMU is generated, is the preferable when possible.

FMU Manipulation Toolbox also allows to group FMU's inside FMU Containers.
    """,
    install_requires=[
        "PySide6 >= 6.8.0",
        "xmlschema >= 3.3.1",
        "elementpath >= 4.4.0",
        "colorama >= 0.4.6",
    ],
    license="BSD-2-Clause",
    python_requires=">=3.8",
)

os.remove("fmu_manipulation_toolbox/__version__.py")
