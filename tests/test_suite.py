import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from fmu_manipulation_toolbox.fmu_operations import *
from fmu_manipulation_toolbox.fmu_container import *
from fmu_manipulation_toolbox.assembly import *


class FMUManipulationToolboxTestSuite(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fmu_filename = "operations/bouncing_ball.fmu"

    def assert_identical_files(self, filename1, filename2):
        with open(filename1, mode="rt", newline=None) as a, open(filename2, mode="rt", newline=None) as b:
            self.assertTrue(all(lineA == lineB for lineA, lineB in zip(a, b)))

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
        fmu = FMU(self.fmu_filename)
        operation = OperationAddRemotingWin32()
        fmu.apply_operation(operation)
        fmu.repack("bouncing_ball-win32.fmu")

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

    def test_container_ssp(self):
        assembly = Assembly("bouncing.ssp", fmu_directory=Path("containers/ssp"))
        assembly.make_fmu(dump_json=True)
        self.assert_identical_files("containers/ssp/REF-bouncing-dump.json",
                                    "containers/ssp/bouncing-dump.json")

    def test_container_json_flat(self):
        assembly = Assembly("flat.json", fmu_directory=Path("containers/arch"))
        assembly.make_fmu(dump_json=True)
        self.assert_identical_files("containers/arch/REF-flat-dump.json",
                                    "containers/arch/flat-dump.json")

    def test_container_json_hierarchical(self):
        assembly = Assembly("hierarchical.json", fmu_directory=Path("containers/arch"))
        assembly.make_fmu(dump_json=True)
        self.assert_identical_files("containers/arch/REF-hierarchical-dump.json",
                                    "containers/arch/hierarchical-dump.json")

    def test_container_json_reversed(self):
        assembly = Assembly("reversed.json", fmu_directory=Path("containers/arch"))
        assembly.make_fmu(dump_json=True)
        self.assert_identical_files("containers/arch/REF-reversed-dump.json",
                                    "containers/arch/reversed-dump.json")

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


if __name__ == '__main__':
    unittest.main()
