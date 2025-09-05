from fmu_manipulation_toolbox.operations import FMU, OperationSaveNamesToCSV, OperationStripTopLevel, \
    OperationRenameFromCSV, OperationAddRemotingWin32, OperationGetNames
# 1st Use Case: remove toplevel bus (if any)
fmu = FMU("tests/bouncing_ball.fmu")
operation = OperationStripTopLevel()
fmu.apply_operation(operation)
fmu.repack(r"tests/bouncing_ball-no-tl.fmu")

# 2nd Use Case: Extract names and write a CSV
fmu = FMU("tests/bouncing_ball.fmu")
operation = OperationSaveNamesToCSV("tests/bouncing_ball.csv")
fmu.apply_operation(operation)

# 3rd Use Case: Read CSV and rename FMU ports
fmu = FMU("tests/bouncing_ball.fmu")
operation = OperationRenameFromCSV("tests/bouncing_ball-modified.csv")
fmu.apply_operation(operation)
fmu.repack("tests/bouncing_ball-renamed.fmu")

# 4th Use Case: Add remoting
fmu = FMU("tests/bouncing_ball.fmu")
operation = OperationAddRemotingWin32()
fmu.apply_operation(operation)
fmu.repack("tests/bouncing_ball-win32.fmu")

fmu = FMU("tests/bouncing_ball-renamed.fmu")
fmu.apply_operation(OperationGetNames())
