class Help:
    _usage = {
        '-h': "display help.",
        '-input': "this option is mandatory to specify the filename of the FMU to be loaded.",

        '-output': "this option is used to specify the filename of the FMU to be created after manipulations."
                   " If it is not provided, no new fmu will be saved and some manipulations can be lost.",

        '-remove-toplevel': "rename the ports of the input fmu by striping all characters until the first '.' "
                            "(toplevel bus). If no '.' is present, the port won't be renamed. Resulting fmu should be "
                            "saved by using -output option. Note: before version 1.2.6, this option was spelled  "
                            "-remove-toplel.",

        '-merge-toplevel': "replace first '.' by an '_' on every port name.",

        '-trim-until': "remove a prefix from port name.  Example '-trim-until _' : will rename port names of the"
                       " FMU by removing part of the name until the first  '_'. Prefix can be longer than a "
                       "single character. ",

        '-remove-regexp': "remove ports that match the regular-expression.  Other ports will be kept. Resulting "
                          "fmu should be saved by using -output option. This option is available from version 1.1. "
                          "See https://en.wikipedia.org/wiki/Regular_expression to have more detail of expected "
                          "format.",

        '-keep-only-regexp': "keep only ports that match the regular-expression.  Other ports will be removed. "
                             "Resulting fmu should be saved by using -output option. This option is available from "
                             "version 1.1. See https://en.wikipedia.org/wiki/Regular_expression to have more detail "
                             "of expected format.",

        '-remove-all': "equivalent to '-remove-regexp .*'. Typical use case is to use it with -only-* options. "
                       "Example:  in order ro suppress all parameters of FMU:   -only-parameters -remove-all",

        '-dump-csv': "list all names of the ports of the input fmu and store them inside path/to/list.csv. "
                     "This file is ';' separated. It contains two columns in order to be easily reused by "
                     "-rename-from-csv option.",

        '-rename-from-csv': "rename the ports of fmu accordingly to path/to/translation.csv. This file is ';' "
                            "separated. It contains two columns. First column contains original names. Second column "
                            "contains new names. * If a port is not found in the file, it won't be renamed. This is "
                            "working with version > 1.2.6. It is safer to keep ALL port in csv. * If the new name is"
                            " empty, the port will be removed. This is working starting version 1.1. * If a name in "
                            "the file is not present in input FMU, it will be ignored. (no warning will be issued). "
                            "Resulting fmu should be saved by using -output option.",

        '-add-remoting-win32': "this option is windows specific. It will add 'win32' interface to a 'win64' fmu."
                               " Please upgrade to version 1.2.1 before using this option. Resulting fmu should be"
                               " saved by using -output option.",

        '-add-remoting-win64': "this option is windows specific. It will add 'win64' interface to a 'win32' fmu."
                               " Please upgrade to version 1.2.1 before using this option. Resulting fmu should be"
                               " saved by using -output option.",

        '-add-frontend-win32': "this option is windows specific. It can be used with 'win32' fmu. At simulation time, "
                               "the FMU will spawn a dedicated process tu run the model. This option is available from "
                               "version 1.4. Resulting fmu should be saved by using -output option.",

        '-add-frontend-win64': "this option is windows specific. It can be used with 'win64' fmu. At simulation time, "
                               "the FMU will spawn a dedicated process tu run the model. This option is available from "
                               "version 1.4. Resulting fmu should be saved by using -output option.",

        '-extract-descriptor': "save the modelDescription.xml into the specified location. If modification options "
                               "(like -rename-from-csv or -remove-toplevel are set), the saved file will contain "
                               "modification. This option is available from version 1.1.",

        '-remove-sources': "Remove sources folder from the FMU. This option is available from version 1.3.",

        '-only-parameters': "apply operation only on ports with  causality = 'parameter'. This "
                            "option is available from version 1.3.",

        '-only-inputs': "apply operation only on ports with  causality = 'parameter'. This "
                        "option is available from version 1.3.",

        '-only-outputs': "apply operation only on ports with  causality = 'output'. This "
                         "option is available from version 1.3.",

        '-only-locals': "apply operation only on ports with  causality = 'local'. This "
                         "option is available from version 1.9.",

        '-summary': "display useful information regarding the FMU.",

        '-check': "performs some check of FMU and display Errors or Warnings. This is useful to avoid later "
                  "issues when using the FMU.",

        # GUI message
        "gui-apply-only": "Apply operation only on ports with specified causality. If selected, at least one causality "
        "should be selected."
    }

    def usage(self, option):
        return self._usage[option]
