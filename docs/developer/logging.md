# Log messages

Every module of the package logs through one logger, `logging.getLogger("fmu_manipulation_toolbox")`. This page
gives the rules that its messages follow: wording, levels, names, errors and spelling of the standard.

## Where the messages are read

The same message is shown in three places, each of which adds the level itself:

| Reader | Handler | Layout |
|---|---|---|
| Command line tools (`fmutool`, `fmucontainer`, `fmusplit`...) | `setup_logger()` of `cli/utils.py` | `LEVEL    \| message`, coloured by level |
| GUIs (FMU Tool, FMU Container Builder) | `GuiLogHandler` and `LogWidget` of `gui/log.py` | coloured by level, `WARNING: `, `ERROR: ` or `CRITICAL: ` before the message |
| MCP tools and `fmutool-agent` | `_captured_logs()` of `assistant/fmutools.py` | the records, returned to the agent |

A message must therefore read well on its own, without a prefix of its own, whatever the reader.

## Wording

- **A sentence**: it starts with a capital letter and ends with a period, also when it ends with a name or a number.
- **Names between single quotes**: FMU file names, ports, model identifiers, paths, options:
  `Port 'x' is removed.`, `Reading 'bouncing.fmu'.`, `'-input' and '-output' should point to different files.`
- **Paths**: relative to the FMU (`sources/model.c`) or to the working directory when possible.
- **No level in the text**: no `INFO`, `ERROR:`, `FATAL ERROR:`, nor tags such as `READING` or `WRITING`. The
  handlers add the level.
- **No layout in the text**: no alignment by spaces, no ad-hoc indentation or bullets. A list of items is one
  message per item, or one sentence.

| Not | But |
|---|---|
| `READING Input='bouncing.fmu'` | `Reading 'bouncing.fmu'.` |
| `FATAL ERROR: Port x not found` | `Port 'x' not found.` (level `CRITICAL`) |
| `Remoting nb input port: 3` | `Remoting: 3 input ports.` |
| `Modified version saved as out.fmu.` | `Modified version saved as 'out.fmu'.` |

## Levels

| Level | Use | Example |
|---|---|---|
| `DEBUG` | Optional message, to help understand the internal mechanisms (command lines, internal steps). | `Remove tag <Annotations> from modelDescription.xml.` |
| `INFO` | General message, to follow the progress of the tool. | `Reading 'bouncing.fmu'.` |
| `WARNING` | Important message. | `FMU 'a.fmu' does not specify a preferred step size.` |
| `ERROR` | An error that is not fatal: a result is produced, but it may differ from the expected one. A checker that finds a non-compliance logs an `ERROR`. | `valueReference 3 is used by 'x' and 'y' (FMI-3 §2.4.7.4).` |
| `CRITICAL` | An error that prevents producing a result: a usage error of the command line, a failed operation, an FMU that cannot be read. | `'-input' and '-output' should point to different files.` |

The records of level `ERROR` and above are counted by `ErrorCounter` (`cli/utils.py`): `fmutool -check` exits with
`ExitCode.CHECK_FAILED` when it counted any. A message must not be logged at `ERROR` or above to draw attention:
`WARNING` is meant for that.

## Errors

- A failure of an operation is **raised**, not logged: `OperationError` or `FMUError` (`operations.py`),
  `AssemblyError` (`assembly.py`), `FMUContainerError` (`container/errors.py`). Its text follows the rules of this
  page, since it is what the caller logs.
- The caller (command line tool, GUI, MCP tool) catches it and logs it **once**, at `CRITICAL`. The command line
  tools then exit with the matching `ExitCode`.
- An error is never logged then ignored: either the operation goes on and the message is an `ERROR` (the result may
  differ from the expected one), or it stops and the error is raised.
- An unexpected exception (any other type) is logged with its type, e.g. `KeyError: 'x'`, so that the message is not
  reduced to `'x'`.

## Spelling of the standard

- `FMI-2` and `FMI-3`, also before a section of the standard: `FMI-3 §2.4.7`.
- The layered standards keep their name: `FMI-LS-BUS`, `FMI-LS-XCP`, `FMI-LS-REF`.
- The same spelling is used in the comments, the docstrings and the documentation. The files copied from the
  standard (`resources/fmi*/`, FMI headers) are not changed.

## Tests

A test that asserts on the text of a message is updated with the message, and keeps checking its level (with
`caplog`, `record.levelno`) as well as its text.
