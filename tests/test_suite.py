import unittest
import sys
from pathlib import Path
from fmpy.simulation import simulate_fmu
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from fmu_manipulation_toolbox.operations import *
from fmu_manipulation_toolbox.remoting import *
from fmu_manipulation_toolbox.container import *
from fmu_manipulation_toolbox.assembly import *
from fmu_manipulation_toolbox.cli.fmutool import fmutool
from fmu_manipulation_toolbox.cli.fmusplit import fmusplit
from fmu_manipulation_toolbox.cli.fmucontainer import fmucontainer

class FMUManipulationToolboxTestSuite(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fmu_filename = "operations/bouncing_ball.fmu"

    def assert_simulation(self, filename: Union[Path, str], step_size: Optional[float] = None):
        if isinstance(filename, str):
            filename = Path(filename)
        result_filename = filename.with_name("results-" + filename.with_suffix(".csv").name)
        ref_filename = result_filename.with_stem("REF-" + result_filename.stem)

        result = simulate_fmu(filename, step_size=step_size, stop_time=10, relative_tolerance=1e-9,
                              output_interval=step_size, validate=True)

        np.savetxt(result_filename, result, delimiter=',', fmt="%.5e")

        self.assert_identical_files(result_filename, ref_filename)

    def assert_identical_files(self, filename1, filename2):
        with open(filename1, mode="rt", newline=None) as a, open(filename2, mode="rt", newline=None) as b:
            self.assertTrue(all(lineA == lineB for lineA, lineB in zip(a, b)))

    @staticmethod
    def assert_identical_files_but_guid(filename1, filename2):
        with open(filename1, mode="rt", newline=None) as a, open(filename2, mode="rt", newline=None) as b:
            for lineA, lineB in zip(a, b):
                if not "guid" in lineA and not lineA == lineB:
                    return False
        return True

    def assert_names_match_ref(self, fmu_filename):
        fmu = FMU(fmu_filename)
        csv_filename = Path(fmu_filename).with_suffix(".csv")
        ref_filename = csv_filename.with_stem("REF-"+csv_filename.stem)
        operation = OperationSaveNamesToCSV(csv_filename)
        fmu.apply_operation(operation)
        self.assert_identical_files(ref_filename, csv_filename)

    def assert_operation_match_ref(self, fmu_filename, operation):
        fmu = FMU(self.fmu_filename)
        fmu.apply_operation(operation)
        fmu.repack(fmu_filename)
        self.assert_names_match_ref(fmu_filename)

    def test_strip_top_level(self):
        self.assert_operation_match_ref("operations/bouncing_ball-no-tl.fmu", OperationStripTopLevel())

    def test_save_names_to_CSV(self):
        self.assert_names_match_ref("operations/bouncing_ball.fmu")

    def test_rename_from_CSV(self):
        self.assert_operation_match_ref("operations/bouncing_ball-renamed.fmu",
                                        OperationRenameFromCSV("operations/bouncing_ball-modified.csv"))

    @unittest.skipUnless(sys.platform.startswith("win"), "Supported only on Windows")
    def test_add_remoting_win32(self):
        fmu = FMU("remoting/bouncing_ball-win32.fmu")
        operation = OperationAddRemotingWin64()
        fmu.apply_operation(operation)
        fmu.repack("remoting/bouncing_ball-win64.fmu")
        self.assert_simulation("remoting/bouncing_ball-win32.fmu")
        self.assert_simulation("remoting/bouncing_ball-win64.fmu")

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
            self.assert_simulation("containers/start/slx.fmu")

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
        sys.argv = ['fmutool', '-input', 'operations/bouncing_ball.fmu', '-summary', '-check', '-dump-csv',
                 'operations/cli-bouncing_ball.csv']
        fmutool()
        self.assert_identical_files("operations/cli-bouncing_ball.csv", "operations/REF-bouncing_ball.csv")

    def test_fmucontainer_csv(self):
        sys.argv = ['fmucontainer', '-container', 'cli-bouncing.csv', '-fmu-directory', 'containers/bouncing_ball',
                    '-mt', '-debug']
        fmucontainer()
        self.assert_identical_files("containers/bouncing_ball/REF-container.txt",
                                    "containers/bouncing_ball/cli-bouncing/resources/container.txt")

    def test_fmucontainer_json(self):
        sys.argv = ['fmucontainer', '-fmu-directory', 'containers/arch', '-container', 'cli-flat.json', '-dump']
        fmucontainer()
        self.assert_identical_files("containers/arch/REF-cli-flat-dump.json",
                                    "containers/arch/cli-flat-dump.json")

    def test_fmusplit(self):
        sys.argv = ["fmusplit", "-fmu", "containers/ssp/bouncing.fmu"]
        fmusplit()
        self.assertTrue(Path("containers/ssp/bouncing.dir/bb_position.fmu").exists())
        self.assertTrue(Path("containers/ssp/bouncing.dir/bb_velocity.fmu").exists())
        self.assert_identical_files("containers/ssp/REF-split-bouncing.json",
                                    "containers/ssp/bouncing.dir/bouncing.json")


if __name__ == '__main__':
    unittest.main()
