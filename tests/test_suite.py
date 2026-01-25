import hashlib
import numpy as np
import pytest
import sys

from pathlib import Path
from fmpy.simulation import simulate_fmu
from fmpy.validation import validate_fmu

sys.path.insert(0, str(Path(__file__).parent.parent))
from fmu_manipulation_toolbox.operations import *
from fmu_manipulation_toolbox.checker import *
from fmu_manipulation_toolbox.remoting import *
from fmu_manipulation_toolbox.container import *
from fmu_manipulation_toolbox.assembly import *
from fmu_manipulation_toolbox.cli.fmusplit import fmusplit
from fmu_manipulation_toolbox.cli.fmucontainer import fmucontainer
from fmu_manipulation_toolbox.cli.fmutool import fmutool
from fmu_manipulation_toolbox.cli.datalog2pcap import datalog2pcap


class TestSuite:
    def assert_simulation(self, filename: Union[Path, str], step_size: Optional[float] = None):
        if isinstance(filename, str):
            filename = Path(filename)
        result_filename = filename.with_name("results-" + filename.with_suffix(".csv").name)
        ref_filename = result_filename.with_stem("REF-" + result_filename.stem)

        result = simulate_fmu(filename, step_size=step_size, stop_time=10,
                              output_interval=step_size, validate=True)

        np.savetxt(result_filename, result, delimiter=',', fmt="%.5e")

        self.assert_identical_files(result_filename, ref_filename)

    @staticmethod
    def assert_simulation_log(filename: Union[Path, str], step_size: Optional[float] = None):
        if isinstance(filename, str):
            filename = Path(filename)

        log_filename = filename.with_name("log-" + filename.with_suffix(".txt").name)
        with open(log_filename, "wt") as log_file:
            def fmu_log(*args):
                print(f"{args[-1].decode('utf-8')}", file=log_file)

            simulate_fmu(filename, step_size=step_size, stop_time=10, relative_tolerance=1e-9,
                         output_interval=step_size, validate=True, logger=fmu_log, debug_logging=True)


        ref_filename = log_filename.with_stem("REF-" + log_filename.stem)

        with open(log_filename, mode="rt", newline=None) as a, open(ref_filename, mode="rt", newline=None) as b:
            for i, (lineA, lineB) in enumerate(zip(a, b)):
                if i > 10:
                    assert lineA == lineB, \
                       f"files {log_filename} and {ref_filename} missmatch (excl. GUID):\n" \
                       f"{lineA}\n" \
                       f"vs.\n\n" \
                       f"{lineB}"

    @staticmethod
    def assert_identical_files(filename1, filename2):
        assert Path(filename1).exists(), f"{filename1} does not exist"
        assert Path(filename2).exists(), f"{filename2} does not exist"
        with open(filename1, mode="rt", newline=None) as a, open(filename2, mode="rt", newline=None) as b:
            for lineA, lineB in zip(a, b):
                assert lineA.strip() == lineB.strip(), \
                       f"file {filename1} and {filename2} missmatch (excl. GUID):\n" \
                       f"{lineA.strip()}\n" \
                       f"vs.\n\n" \
                       f"{lineB.strip()}"

    @staticmethod
    def assert_identical_files_but_guid(filename1, filename2):
        keywords = ("guid", "author", "generationDateAndTime", "instantiationToken")
        with open(filename1, mode="rt", newline=None) as a, open(filename2, mode="rt", newline=None) as b:
            for lineA, lineB in zip(a, b):
                skip = False
                for keyword in keywords:
                    if keyword in lineA:
                        skip = True
                        break
                assert skip or lineA == lineB, \
                       f"file {filename1} and {filename2} missmatch:\n" \
                       f"{lineA}\n" \
                       f"vs.\n\n" \
                       f"{lineB}"

    def assert_names_match_ref(self, fmu_filename):
        fmu = FMU(fmu_filename)
        csv_filename = Path(fmu_filename).with_suffix(".csv")
        ref_filename = csv_filename.with_stem("REF-"+csv_filename.stem)
        operation = OperationSaveNamesToCSV(csv_filename)
        fmu.apply_operation(operation)
        self.assert_identical_files(ref_filename, csv_filename)

    def assert_operation_match_ref(self, fmu_filename, operation):
        fmu = FMU("operations/bouncing_ball.fmu")
        fmu.apply_operation(operation)
        fmu.repack(fmu_filename)
        self.assert_names_match_ref(fmu_filename)

    @staticmethod
    def assert_md5(filename, expected_md5):
        hash_md5 = hashlib.md5()
        with open(filename, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        print(f"{filename}: {expected_md5} {hash_md5.hexdigest()}")
        assert hash_md5.hexdigest() == expected_md5 ,\
            f"Wrong md5 hash for {filename}. Expected {expected_md5} but got {hash_md5.hexdigest()}"

    @staticmethod
    def assert_file_exist(path):
        assert Path(path).exists()

    def test_strip_top_level(self):
        self.assert_operation_match_ref("operations/bouncing_ball-no-tl.fmu", OperationStripTopLevel())

    def test_save_names_to_csv(self):
        self.assert_names_match_ref("operations/bouncing_ball.fmu")

    def test_rename_from_csv(self):
        self.assert_operation_match_ref("operations/bouncing_ball-renamed.fmu",
                                        OperationRenameFromCSV("operations/bouncing_ball-modified.csv"))

    #@unittest.skipUnless(sys.platform.startswith("win"), "Supported only on Windows")
    @pytest.mark.skipif(not sys.platform == "win32", reason="does run only on windows")
    def test_add_remoting_win32(self):
        fmu = FMU("remoting/bouncing_ball-win32.fmu")
        operation = OperationAddRemotingWin64()
        fmu.apply_operation(operation)
        fmu.repack("remoting/bouncing_ball-win64.fmu")
        self.assert_simulation("remoting/bouncing_ball-win32.fmu")
        self.assert_simulation("remoting/bouncing_ball-win64.fmu")

    def test_checker(self):
        fmu = FMU("operations/bouncing_ball.fmu")
        fmu.apply_operation(OperationGenericCheck())

    def test_remove_regexp(self):
        self.assert_operation_match_ref("operations/bouncing_ball-removed.fmu",
                                        OperationRemoveRegexp("e"))

    def test_keep_only_regexp(self):
        self.assert_operation_match_ref("operations/bouncing_ball-keeponly.fmu",
                                        OperationKeepOnlyRegexp("e"))

    def test_container_bouncing_ball(self):
        assembly = Assembly("bouncing.csv", fmu_directory=Path("containers/bouncing_ball"), mt=True, debug=True)
        assembly.write_json("bouncing.json")
        assembly.make_fmu()
        assembly.write_csv("bouncing2.csv")
        self.assert_identical_files("containers/bouncing_ball/REF-container.txt",
                                    "containers/bouncing_ball/bouncing/resources/container.txt")
        self.assert_identical_files("containers/bouncing_ball/REF-bouncing.json",
                                    "containers/bouncing_ball/bouncing.json")
        if os.name == 'nt':
            self.assert_simulation("containers/bouncing_ball/bouncing.fmu")

    def test_container_bouncing_ball_seq(self):
        assembly = Assembly("bouncing-seq.csv", fmu_directory=Path("containers/bouncing_ball"), mt=True, debug=True,
                            sequential=True)
        assembly.write_json("bouncing-seq.json")
        assembly.make_fmu()
        self.assert_identical_files("containers/bouncing_ball/REF-container-seq.txt",
                                    "containers/bouncing_ball/bouncing-seq/resources/container.txt")
        self.assert_identical_files("containers/bouncing_ball/REF-bouncing-seq.json",
                                    "containers/bouncing_ball/bouncing-seq.json")
        if os.name == 'nt':
            self.assert_simulation("containers/bouncing_ball/bouncing-seq.fmu")

    def test_container_bouncing_ball_profiling(self):
        assembly = Assembly("bouncing-profiling.csv", fmu_directory=Path("containers/bouncing_ball"), profiling=True,
                            debug=True)
        assembly.write_json("bouncing-profiling.json")
        assembly.make_fmu()
        self.assert_identical_files("containers/bouncing_ball/REF-container-profiling.txt",
                                    "containers/bouncing_ball/bouncing-profiling/resources/container.txt")
        self.assert_identical_files("containers/bouncing_ball/REF-bouncing-profiling.json",
                                    "containers/bouncing_ball/bouncing-profiling.json")
        self.assert_identical_files_but_guid("containers/bouncing_ball/REF-modelDescription-profiling.xml",
                                             "containers/bouncing_ball/bouncing-profiling/modelDescription.xml")
        if os.name == 'nt':
            self.assert_simulation("containers/bouncing_ball/bouncing-profiling.fmu")

    def test_container_bouncing_ball_profiling_3(self):
        assembly = Assembly("bouncing-3.csv", fmu_directory=Path("containers/bouncing_ball"), profiling=True,
                            debug=True)
        assembly.make_fmu(fmi_version=3)
        self.assert_identical_files("containers/bouncing_ball/REF-container-3.txt",
                                    "containers/bouncing_ball/bouncing-3/resources/container.txt")
        self.assert_identical_files_but_guid("containers/bouncing_ball/REF-modelDescription-3.xml",
                                             "containers/bouncing_ball/bouncing-3/modelDescription.xml")
        if os.name == 'nt':
            self.assert_simulation("containers/bouncing_ball/bouncing-3.fmu")

    def test_container_ssp(self):
        assembly = Assembly("bouncing.ssp", fmu_directory=Path("containers/ssp"))
        assembly.make_fmu(dump_json=True)
        self.assert_identical_files("containers/ssp/REF-bouncing-dump.json",
                                    "containers/ssp/bouncing-dump.json")
        if os.name == 'nt':
            self.assert_simulation("containers/ssp/bouncing.fmu")

    def test_container_json_flat(self):
        assembly = Assembly("flat.json", fmu_directory=Path("containers/arch"))
        assembly.make_fmu(dump_json=True)
        self.assert_identical_files("containers/arch/REF-flat-dump.json",
                                    "containers/arch/flat-dump.json")
        if os.name == 'nt':
            self.assert_simulation("containers/arch/flat.fmu")

    def test_container_subdir_flat(self):
        container = FMUContainer("sub.fmu", fmu_directory=Path("containers/arch"))
        container.get_fmu("subdir/gain2.fmu")
        container.get_fmu("integrate.fmu")
        container.get_fmu("sine.fmu")
        container.add_implicit_rule()
        container.make_fmu("sub.fmu", step_size=0.5)
        if os.name == 'nt':
            self.assert_simulation("containers/arch/sub.fmu")

    def test_container_json_hierarchical(self):
        assembly = Assembly("hierarchical.json", fmu_directory=Path("containers/arch"))
        assembly.make_fmu(dump_json=True)
        self.assert_identical_files("containers/arch/REF-hierarchical-dump.json",
                                    "containers/arch/hierarchical-dump.json")
        if os.name == 'nt':
            self.assert_simulation("containers/arch/hierarchical.fmu")

    def test_container_json_reversed(self):
        assembly = Assembly("reversed.json", fmu_directory=Path("containers/arch"))
        assembly.make_fmu(dump_json=True)
        self.assert_identical_files("containers/arch/REF-reversed-dump.json",
                                    "containers/arch/reversed-dump.json")
        if os.name == 'nt':
            self.assert_simulation("containers/arch/reversed.fmu")

    def test_container_start(self):
        assembly = Assembly("slx.json", fmu_directory=Path("containers/start"), debug=True)
        assembly.make_fmu()
        self.assert_identical_files("containers/start/REF-container.txt",
                                    "containers/start/container-slx/resources/container.txt")
        self.assert_identical_files_but_guid("containers/start/REF-modelDescription.xml",
                                             "containers/start/container-slx/modelDescription.xml")
        if os.name == 'nt':
            self.assert_simulation("containers/start/container-slx.fmu")

    def test_container_vanderpol(self):
        self.assert_simulation("containers/VanDerPol/VanDerPol.fmu", 0.1)
        assembly = Assembly("VanDerPol.json", fmu_directory=Path("containers/VanDerPol"))
        assembly.make_fmu()
        self.assert_simulation("containers/VanDerPol/VanDerPol-Container.fmu", 0.1)


    def test_container_vanderpol_vr(self):
        assembly = Assembly("VanDerPol-vr.json", fmu_directory=Path("containers/VanDerPol"))
        assembly.make_fmu()
        if os.name == 'nt':
            self.assert_simulation("containers/VanDerPol/VanDerPol-vr2.fmu", 0.1)

    def test_fmi3_pt2(self):
        assembly = Assembly("passthrough.json", fmu_directory=Path("fmi3/passthrough"), debug=True)
        assembly.make_fmu(fmi_version=2)
        self.assert_identical_files("fmi3/passthrough/REF-container.txt",
                                    "fmi3/passthrough/container-passthrough/resources/container.txt")
        if os.name == 'nt':
            self.assert_simulation("fmi3/passthrough/container-passthrough.fmu")

    def test_container_move(self):
        #bb = Assembly("bouncing.csv", fmu_directory=Path("containers/bouncing_ball"))
        #links = bb.root.get_fmu_connections("bb_position.fmu")
        #print("Links: ", links)
        #bb.write_json("bouncing.json")
        assembly = Assembly("nested.json", fmu_directory=Path("containers/arch"))
        fmu_name = "fmu1b.fmu"
        links_fmu1b = assembly.root.children["level1.fmu"].get_fmu_connections("fmu1b.fmu")

        print("RESULTS:")
        for link in links_fmu1b:
            print(f"{link}")

        links_fmu0a = assembly.root.get_fmu_connections("fmu0a.fmu")
        print("RESULTS:")
        for link in links_fmu0a:
            print(f"{link}")

    def test_fmutool(self):

        sys.argv = ['fmutool',
                    '-input', 'operations/bouncing_ball.fmu', '-summary', '-check', '-dump-csv',
                    'operations/cli-bouncing_ball.csv']
        fmutool()

        self.assert_identical_files("operations/cli-bouncing_ball.csv", "operations/REF-bouncing_ball.csv")

    def test_fmucontainer_csv(self):
        sys.argv = ['fmucontainer',
                    '-container', 'cli-bouncing.csv', '-fmu-directory', 'containers/bouncing_ball',
                    '-mt', '-debug']
        fmucontainer()
        self.assert_identical_files("containers/bouncing_ball/REF-container.txt",
                                    "containers/bouncing_ball/cli-bouncing/resources/container.txt")

    def test_fmucontainer_json(self):
        sys.argv = ['fmucontainer',
                    '-fmu-directory', 'containers/arch', '-container', 'cli-flat.json', '-dump']
        fmucontainer()
        self.assert_identical_files("containers/arch/REF-cli-flat-dump.json",
                                    "containers/arch/cli-flat-dump.json")

    def test_fmusplit(self):
        sys.argv = ['fmusplit',
                    "-fmu", "containers/ssp/bouncing.fmu"]
        fmusplit()
        assert Path("containers/ssp/bouncing.dir/bb_position.fmu").exists()
        assert Path("containers/ssp/bouncing.dir/bb_velocity.fmu").exists()
        self.assert_identical_files("containers/ssp/REF-split-bouncing.json",
                                    "containers/ssp/bouncing.dir/bouncing.json")

    def test_ls_bus_nodes_and_bus(self):
        assembly = Assembly("bus+nodes.json", fmu_directory=Path("ls-bus"))
        assembly.make_fmu(fmi_version=3)
        self.assert_simulation_log("ls-bus/bus+nodes.fmu", 0.1)

    def test_ls_bus_nodes_only(self):
        assembly = Assembly("nodes-only.json", fmu_directory=Path("ls-bus"))
        assembly.make_fmu(fmi_version=3, datalog=True)
        self.assert_simulation_log("ls-bus/nodes-only.fmu", 0.1)

    def test_datalog(self):
        assembly = Assembly("bouncing.csv", fmu_directory=Path("containers/bouncing_ball"), mt=True, debug=True)
        assembly.make_fmu(filename="bouncing-datalog.fmu", datalog=True)
        self.assert_identical_files("containers/bouncing_ball/bouncing-datalog/resources/datalog.txt",
                                    "containers/bouncing_ball/REF-datalog.txt")
        if os.name == 'nt':
            self.assert_simulation("containers/bouncing_ball/bouncing-datalog.fmu")
            self.assert_file_exist("bouncing-datalog.csv")

    def test_datalog3(self):
        assembly = Assembly("VanDerPol.json", fmu_directory=Path("containers/VanDerPol"), mt=True, debug=True)
        assembly.make_fmu(filename="VanDerPol-datalog.fmu", datalog=True, fmi_version=3)
        self.assert_identical_files("containers/VanDerPol/VanDerPol-datalog/resources/datalog.txt",
                                    "containers/VanDerPol/REF-datalog.txt")
        self.assert_simulation("containers/VanDerPol/VanDerPol-datalog.fmu", 0.1)
        self.assert_file_exist("VanDerPol-Container-datalog.csv")

    def test_datalog_pcap(self):
        sys.argv = ['datalog2pcap',
                    '-can', 'ls-bus/REF-nodes-only-datalog.csv']
        datalog2pcap()

        self.assert_md5("ls-bus/REF-nodes-only-datalog.pcap", "ceab6b0161dbc93458bd47c057e80375")

    def test_array(self):
        fmu = FMU("array/StateSpace.fmu")
        fmu.apply_operation(OperationSummary())
        fmu.save_descriptor("array/modelDescription.xml")
        fmu.repack("array/StateSpace-copy.fmu")
        validate_fmu("array/StateSpace-copy.fmu")
        self.assert_identical_files("array/REF-modelDescription.xml", "array/modelDescription.xml")
