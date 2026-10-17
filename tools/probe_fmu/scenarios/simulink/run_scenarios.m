function run_scenarios(output_dir, names)
%RUN_SCENARIOS Simulate the Simulink models of the comparison scenarios.
%   RUN_SCENARIOS(OUTPUT_DIR) simulates every model built by build_scenarios in OUTPUT_DIR;
%   RUN_SCENARIOS(OUTPUT_DIR, NAMES) only those of the cell array NAMES.
%
%   Each model runs with OUTPUT_DIR/<scenario>/simulink/ as current folder: the probes write their traces
%   (A.csv, B.csv, C.csv) there. The script also writes in that folder:
%     log.txt      the messages of the simulation (command window and warnings of the simulation)
%     wall.txt     the wall time of the simulation (s)
%     results.csv  the outputs of the model (root Outports), one line per sample: name,time,value
%   and OUTPUT_DIR/version.txt (MATLAB version and platform).
%   The folder of the probes recorded by build_scenarios (OUTPUT_DIR/probe_dir.txt) is added to the MATLAB path:
%   the models only hold the file names of the FMUs.

    scenarios = probe_scenarios();
    if nargin >= 2 && ~isempty(names)
        scenarios = scenarios(ismember({scenarios.name}, names));
    end
    if ~java.io.File(output_dir).isAbsolute()
        output_dir = fullfile(pwd, output_dir);
    end

    probe_dir = strtrim(fileread(fullfile(output_dir, 'probe_dir.txt')));
    addpath(probe_dir);

    file = fopen(fullfile(output_dir, 'version.txt'), 'w');
    fprintf(file, '%s\n%s\n', evalc('ver'), computer('arch'));
    fclose(file);

    previous = pwd;
    cleanup = onCleanup(@() cd(previous));
    for scenario = scenarios
        model = scenario.name;
        folder = fullfile(output_dir, model, 'simulink');
        cd(folder);
        delete_if_exists('log.txt');
        delete_if_exists('wall.txt');
        diary('log.txt');
        try
            load_system(fullfile(folder, [model '.slx']));
            start = tic;
            out = sim(model, 'CaptureErrors', 'on');
            wall = toc(start);
            if report_diagnostics(out)
                fprintf('%s: FAILED (see above)\n', model);
            else
                file = fopen('wall.txt', 'w');
                fprintf(file, '%.6f\n', wall);
                fclose(file);
                write_results(out, 'results.csv');
                fprintf('%s: done in %.3f s\n', model, wall);
            end
        catch err
            fprintf('%s: FAILED: %s\n', model, err.message);
        end
        diary('off');
        if bdIsLoaded(model)
            close_system(model, 0);
        end
    end
end


function failed = report_diagnostics(out)
    % Errors and warnings of the simulation (also shown in the Diagnostic Viewer). True if the simulation failed.
    failed = false;
    try
        info = out.SimulationMetadata.ExecutionInfo;
        if ~isempty(info.ErrorDiagnostic)
            failed = true;
            fprintf('ERROR: %s\n', info.ErrorDiagnostic.Diagnostic.message);
        end
        for k = 1:numel(info.WarningDiagnostics)
            fprintf('WARNING: %s\n', info.WarningDiagnostics(k).Diagnostic.message);
        end
    catch err
        fprintf('Cannot read the diagnostics of the simulation: %s\n', err.message);
    end
end


function write_results(out, filename)
    % Outputs saved in 'yout' (Dataset of the root Outports): name,time,value (the ports may have different rates).
    try
        yout = out.get('yout');
        file = fopen(filename, 'w');
        fprintf(file, 'name,time,value\n');
        for k = 1:yout.numElements
            element = yout.getElement(k);
            values = element.Values;
            data = double(values.Data(:));
            for i = 1:numel(values.Time)
                fprintf(file, '%s,%.17g,%.17g\n', element.Name, values.Time(i), data(i));
            end
        end
        fclose(file);
    catch err
        fprintf('Cannot write %s: %s\n', filename, err.message);
    end
end


function delete_if_exists(filename)
    if exist(filename, 'file')
        delete(filename);
    end
end
