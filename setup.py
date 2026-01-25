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
    packages=["fmu_manipulation_toolbox", "fmu_manipulation_toolbox.cli"],
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
                                      "fmusplit = fmu_manipulation_toolbox.cli.fmusplit:fmusplit",
                                      "datalog2pcap = fmu_manipulation_toolbox.cli.datalog2pcap:datalog2pcap",
                                      ],
                  "gui_scripts": ["fmutool-gui = fmu_manipulation_toolbox.gui.gui:main"]
                  },
    author=author,
    url="https://github.com/grouperenault/fmu_manipulation_toolbox/",
    description="FMU Manipulation Toolbox is a python package which helps to analyze, modify or combine "
                "Functional Mock-up Units (FMUs) without recompilation.",
    long_description="""FMU Manipulation Toolbox is a python package which helps to analyze, modify or combine
[Functional Mock-up Units (FMUs)](https://fmi-standard.org/) without recompilation. It is highly customizable and comes with
a Python API.

FMU Manipulation Toolbox can be used in different ways:
- Using a Graphical User Interface: suitable for end users
- Using a Command Line Interface: useful for scripting and automation
- Using a Python API: the most efficient option for automation (CI/CD, transformation scripts, ...))

Major features:
- Analyze FMU content: list ports and their attributes, check compliance of `ModelDescription.xml` with XSD, etc.
- Alter FMU by modifying its `REF-modelDescription.xml` file. NOTE: manipulating this file can be a risky.
  When possible, it is preferable to communicate with the FMU developer and adapt the FMU generation process.
- Add binary interfaces. Typical use case is porting a 32-bit FMUs to 64-bit systems (or vice et versa). 
- Combine FMUs into [FMU Containers](doc/container.md) and allow your favourite FMI tool to orchestrate complex assembly of FMUs.

FMI versions 2.0 and 3.0 are supported.
    """,
    long_description_content_type="text/markdown",
    install_requires=[
        "PySide6 >= 6.8.0",
        "xmlschema >= 3.3.1",
        "elementpath >= 4.4.0",
        "colorama >= 0.4.6",
    ],
    license="BSD-2-Clause",
    python_requires=">=3.9",
)

os.remove("fmu_manipulation_toolbox/__version__.py")
