"""The SSP reader on files laid out as other tools write them (plan `ssp_beta`, step 6).

No third-party SSP file is redistributed (D12): the tests build each SSP the way a tool lays it out, around the
Reference FMUs of `tests/data`. `bouncing.ssp` (easySSP, `test_ssp.py`) stays the real file of another tool.

- OMSimulator: a root system holding a sub-system (a nested container), an external `.ssv` of the archive
  addressing a parameter by its hierarchical name, a `DefaultExperiment` and the `org.openmodelica` annotations.
- MIC modeler (non-regression of modeler-bridge, D13): SSP 2.0, architecture wires between `aw.<peer>`
  connectors, connectors with units, a component without `source`, the `com.renault.micmodeler` annotations.
"""
import logging
import zipfile

import pytest

from fmu_manipulation_toolbox.assembly import Assembly

pytestmark = [pytest.mark.integration]

NAMESPACES = ('xmlns:ssd="http://ssp-standard.org/SSP1/SystemStructureDescription" '
              'xmlns:ssc="http://ssp-standard.org/SSP1/SystemStructureCommon" '
              'xmlns:ssv="http://ssp-standard.org/SSP1/SystemStructureParameterValues"')

OMSIMULATOR_SSD = f'''<?xml version="1.0" encoding="UTF-8"?>
<ssd:SystemStructureDescription {NAMESPACES} xmlns:oms="https://raw.githubusercontent.com/OpenModelica/OMSimulator/master/schema/oms.xsd" name="model" version="1.0">
  <ssd:System name="root" description="">
    <ssd:Connectors>
      <ssd:Connector name="height" kind="output"><ssc:Real/></ssd:Connector>
    </ssd:Connectors>
    <ssd:ParameterBindings>
      <ssd:ParameterBinding source="resources/root.ssv"/>
    </ssd:ParameterBindings>
    <ssd:Elements>
      <ssd:System name="ball" description="">
        <ssd:Connectors>
          <ssd:Connector name="h" kind="output"><ssc:Real/></ssd:Connector>
        </ssd:Connectors>
        <ssd:Elements>
          <ssd:Component name="bb" type="application/x-fmu-sharedlibrary" source="resources/0001_bb.fmu">
            <ssd:Connectors>
              <ssd:Connector name="h" kind="output"><ssc:Real/></ssd:Connector>
              <ssd:Connector name="g" kind="parameter"><ssc:Real/></ssd:Connector>
            </ssd:Connectors>
          </ssd:Component>
        </ssd:Elements>
        <ssd:Connections>
          <ssd:Connection startElement="bb" startConnector="h" endElement="" endConnector="h"/>
        </ssd:Connections>
        <ssd:Annotations>
          <ssc:Annotation type="org.openmodelica">
            <oms:Annotations><oms:SimulationInformation><oms:FixedStepMaster description="oms-ma" stepSize="0.01"/>
            </oms:SimulationInformation></oms:Annotations>
          </ssc:Annotation>
        </ssd:Annotations>
      </ssd:System>
    </ssd:Elements>
    <ssd:Connections>
      <ssd:Connection startElement="ball" startConnector="h" endConnector="height"/>
    </ssd:Connections>
  </ssd:System>
  <ssd:DefaultExperiment startTime="0" stopTime="0.5">
    <ssd:Annotations>
      <ssc:Annotation type="org.openmodelica">
        <oms:Annotations><oms:SimulationInformation resultFile="model_res.mat" loggingInterval="0"/></oms:Annotations>
      </ssc:Annotation>
    </ssd:Annotations>
  </ssd:DefaultExperiment>
</ssd:SystemStructureDescription>
'''

ROOT_SSV = '''<?xml version="1.0" encoding="UTF-8"?>
<ssv:ParameterSet xmlns:ssv="http://ssp-standard.org/SSP1/SystemStructureParameterValues" version="1.0" name="parameters">
  <ssv:Parameters>
    <ssv:Parameter name="ball.bb.g"><ssv:Real value="-1"/></ssv:Parameter>
  </ssv:Parameters>
</ssv:ParameterSet>
'''


def _omsimulator_ssp(data_dir, directory):
    with zipfile.ZipFile(directory / "model.ssp", "w") as ssp:
        ssp.writestr("SystemStructure.ssd", OMSIMULATOR_SSD)
        ssp.writestr("resources/root.ssv", ROOT_SSV)
        ssp.write(data_dir / "compile" / "3.0" / "BouncingBall.fmu", "resources/0001_bb.fmu")


def test_an_omsimulator_layout_is_read(data_dir, tmp_path, monkeypatch, caplog):
    _omsimulator_ssp(data_dir, tmp_path)
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        root = Assembly("model.ssp").root

    ball = root.children["ball.fmu"]
    assert (root.start_time, root.stop_time) == (0.0, 0.5)
    assert [(port.fmu_name, port.port_name, name) for port, name in root.output_ports.items()] == \
        [("ball.fmu", "h", "height")]
    assert [(port.port_name, name) for port, name in ball.output_ports.items()] == [("h", "h")]
    assert {(port.fmu_name, port.port_name): value for port, value in ball.start_values.items()} == \
        {("model.dir/resources/bb.fmu", "g"): "-1"}
    assert "SSP schema" not in caplog.text


@pytest.mark.needs_fmpy
@pytest.mark.needs_container
@pytest.mark.slow
def test_an_omsimulator_layout_simulates_with_its_parameter(data_dir, tmp_path, monkeypatch):
    """Nested container, value from the root `.ssv`: g = -1, so h(0.5) = 1 - 0.5²/2 (no bounce yet)."""
    from _helpers.simulation import simulate

    _omsimulator_ssp(data_dir, tmp_path)
    monkeypatch.chdir(tmp_path)

    Assembly("model.ssp", default_step_size=0.01).make_fmu()
    result = simulate("model.fmu", stop_time=0.5, output=["height"])

    assert result["height"][-1] == pytest.approx(0.875, abs=0.02)


# --------------------------------------------------------------------------- #
#                     MIC modeler: non-regression of modeler-bridge            #
# --------------------------------------------------------------------------- #
MIC_SSD = f'''<?xml version='1.0' encoding='UTF-8'?>
<ssd:SystemStructureDescription xmlns:aw="urn:fmu_manipulation_toolbox:architecture-wire:1" xmlns:mic="urn:com.renault.micmodeler:ssp:1" {NAMESPACES} version="2.0" name="assembly" generationTool="MIC modeler">
  <ssd:System name="assembly">
    <ssd:Elements>
      <ssd:Component name="velocity" source="resources/velocity/v1.fmu">
        <ssd:Connectors>
          <ssd:Connector name="velocity" kind="output"><ssc:Real unit="m/s"/></ssd:Connector>
          <ssd:Connector name="reset" kind="input"><ssc:Boolean/></ssd:Connector>
          <ssd:Connector name="aw.position" kind="output"><ssd:ConnectorGeometry x="1" y="0.5"/></ssd:Connector>
          <ssd:Connector name="aw.gearbox" kind="output"><ssd:ConnectorGeometry x="1" y="0.2"/></ssd:Connector>
        </ssd:Connectors>
        <ssd:ElementGeometry x1="-300" y1="-100" x2="-100" y2="0"/>
        <ssc:MetaData kind="general" type="application/yaml" source="extra/com.renault.micmodeler/library/velocity/v1.yaml"/>
        <ssd:Annotations><ssc:Annotation type="com.renault.micmodeler">
          <mic:Instance formatVersion="1" uuid="00000000-0000-4000-8000-000000000001" version="1"/>
        </ssc:Annotation></ssd:Annotations>
      </ssd:Component>
      <ssd:Component name="position" source="resources/position/v1.fmu">
        <ssd:Connectors>
          <ssd:Connector name="velocity" kind="input"><ssc:Real unit="m/s"/></ssd:Connector>
          <ssd:Connector name="is_ground" kind="output"><ssc:Boolean/></ssd:Connector>
          <ssd:Connector name="position1" kind="output"><ssc:Real unit="m"/></ssd:Connector>
          <ssd:Connector name="aw.velocity" kind="input"><ssd:ConnectorGeometry x="0" y="0.5"/></ssd:Connector>
        </ssd:Connectors>
        <ssd:ElementGeometry x1="100" y1="-100" x2="300" y2="0"/>
      </ssd:Component>
      <ssd:Component name="gearbox">
        <ssd:Connectors>
          <ssd:Connector name="input_speed" kind="input"><ssc:Real unit="rad/s"/></ssd:Connector>
          <ssd:Connector name="aw.velocity" kind="input"/>
        </ssd:Connectors>
      </ssd:Component>
    </ssd:Elements>
    <ssd:Connections>
      <ssd:Connection startElement="velocity" startConnector="aw.position" endElement="position" endConnector="aw.velocity" description="Speed and bounce">
        <ssd:Annotations><ssc:Annotation type="fmu_manipulation_toolbox.architecture-wire">
          <aw:Wire formatVersion="1" orientation="bidirectional"/>
        </ssc:Annotation></ssd:Annotations>
      </ssd:Connection>
      <ssd:Connection startElement="velocity" startConnector="velocity" endElement="position" endConnector="velocity"/>
      <ssd:Connection startElement="position" startConnector="is_ground" endElement="velocity" endConnector="reset"/>
      <ssd:Connection startElement="velocity" startConnector="aw.gearbox" endElement="gearbox" endConnector="aw.velocity">
        <ssd:Annotations><ssc:Annotation type="fmu_manipulation_toolbox.architecture-wire">
          <aw:Wire formatVersion="1" orientation="directed"/>
        </ssc:Annotation></ssd:Annotations>
      </ssd:Connection>
      <ssd:Connection startElement="velocity" startConnector="velocity" endElement="gearbox" endConnector="input_speed"/>
    </ssd:Connections>
  </ssd:System>
  <ssd:Annotations><ssc:Annotation type="com.renault.micmodeler">
    <mic:Assembly formatVersion="1"><mic:View zoom="1" centerX="0" centerY="0"/></mic:Assembly>
  </ssc:Annotation></ssd:Annotations>
</ssd:SystemStructureDescription>
'''


@pytest.mark.needs_container
def test_a_mic_modeler_layout_is_still_read(data_dir, tmp_path, monkeypatch, caplog):
    """Wires kept, links read, the component without source ignored with its connections (even one between
    different units), and the container builds."""
    with zipfile.ZipFile(tmp_path / "assembly.ssp", "w") as ssp:
        ssp.writestr("SystemStructure.ssd", MIC_SSD)
        ssp.write(data_dir / "fmi3" / "bouncing_ball" / "bb_velocity.fmu", "resources/velocity/v1.fmu")
        ssp.write(data_dir / "fmi3" / "bouncing_ball" / "bb_position.fmu", "resources/position/v1.fmu")
        ssp.writestr("extra/com.renault.micmodeler/library/velocity/v1.yaml", "name: velocity\n")
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING, logger="fmu_manipulation_toolbox"):
        assembly = Assembly("assembly.ssp")
    root = assembly.root

    assert [str(link) for link in root.links] == [
        "assembly.dir/resources/velocity/velocity.fmu/velocity -> assembly.dir/resources/position/position.fmu/velocity",
        "assembly.dir/resources/position/position.fmu/is_ground -> assembly.dir/resources/velocity/velocity.fmu/reset"]
    assert [(wire.orientation, wire.description) for wire in root.architecture_wires] == \
        [("bidirectional", "Speed and bounce")]
    assert "Component 'gearbox' has no source FMU" in caplog.text
    assert "SSP schema" not in caplog.text

    assembly.root.auto_output = True
    assembly.make_fmu(fmi_version=3)
    assert zipfile.is_zipfile("assembly.fmu")
