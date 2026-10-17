function build_scenarios(probe_dir, output_dir, names)
%BUILD_SCENARIOS Build the Simulink models of the comparison scenarios.
%   BUILD_SCENARIOS(PROBE_DIR, OUTPUT_DIR) builds every scenario of probe_scenarios.m;
%   BUILD_SCENARIOS(PROBE_DIR, OUTPUT_DIR, NAMES) only those of the cell array NAMES (e.g. {'S1', 'S3'}).
%
%   PROBE_DIR holds the probes compiled for this machine (Probe10ms-host.fmu, Probe20ms-host.fmu,
%   Probe50ms-host.fmu: fmutool -input Probe10ms.fmu -compile-sources -output Probe10ms-host.fmu).
%   The FMU block only accepts a file name on the MATLAB path: PROBE_DIR is added to the path (addpath) and
%   recorded in OUTPUT_DIR/probe_dir.txt for run_scenarios.
%   Each model is saved as OUTPUT_DIR/<scenario>/simulink/<scenario>.slx. The calls that failed (undocumented
%   Simulink names, see probe_simulink_api.m) and the settings to make by hand are listed in
%   OUTPUT_DIR/<scenario>/simulink/build_issues.txt and printed.
%
%   Run the models with run_scenarios(OUTPUT_DIR).

    api = probe_simulink_api();
    scenarios = probe_scenarios();
    if nargin >= 3 && ~isempty(names)
        scenarios = scenarios(ismember({scenarios.name}, names));
    end
    probe_dir = absolute(probe_dir);
    output_dir = absolute(output_dir);
    step_sizes = containers.Map({'Probe10ms', 'Probe20ms', 'Probe50ms'}, {0.01, 0.02, 0.05});

    addpath(probe_dir);
    if ~exist(output_dir, 'dir')
        mkdir(output_dir);
    end
    write_lines(fullfile(output_dir, 'probe_dir.txt'), {probe_dir});

    load_system(api.fmu_library);
    load_system('simulink');
    for scenario = scenarios
        issues = build_scenario(scenario, api, output_dir, step_sizes);
        folder = fullfile(output_dir, scenario.name, 'simulink');
        write_lines(fullfile(folder, 'build_issues.txt'), issues);
        fprintf('%s: %s\n', scenario.name, fullfile(folder, [scenario.name '.slx']));
        for k = 1:numel(issues)
            fprintf('  %s\n', issues{k});
        end
    end
end


function issues = build_scenario(scenario, api, output_dir, step_sizes)
    issues = {};
    model = scenario.name;
    folder = fullfile(output_dir, model, 'simulink');
    if ~exist(folder, 'dir')
        mkdir(folder);
    end
    if bdIsLoaded(model)
        close_system(model, 0);
    end
    new_system(model);
    set_param(model, api.solver{:}, 'StopTime', num2str(scenario.stop_time));
    set_param(model, api.model{:});
    set_param(model, api.multitasking, on_off(scenario.multitasking));

    % FMU blocks
    rates = containers.Map();
    for k = 1:size(scenario.blocks, 1)
        [block, probe] = scenario.blocks{k, :};
        path = [model '/' block];
        position = [100 + 300 * (k - 1), 100, 220 + 300 * (k - 1), 260];
        try
            add_block(api.fmu_block, path, 'Position', position);
        catch err
            close_system(model, 0);
            error('build_scenarios:fmu_block', ...
                  'Cannot add the FMU block "%s": %s\nCorrect api.fmu_block in probe_simulink_api.m.', ...
                  api.fmu_block, err.message);
        end
        set_param(path, api.fmu_name, [probe '-host.fmu']);     % file name only: PROBE_DIR is on the path
        issues = try_set(issues, path, api.input_mapping, api.flat);
        issues = try_set(issues, path, api.output_mapping, api.flat);
        issues = try_set(issues, path, api.sample_time, num2str(step_sizes(probe)));
        rates(block) = step_sizes(probe);
    end

    % Parameters
    for k = 1:size(scenario.parameters, 1)
        [block, variable, value] = scenario.parameters{k, :};
        issues = try_set(issues, [model '/' block], api.parameter_name(variable), value);
    end

    % Start values of inputs: no known programmatic name
    for k = 1:size(scenario.input_starts, 1)
        [block, variable, value] = scenario.input_starts{k, :};
        issues{end + 1} = sprintf('BY HAND: start value of input %s.%s = %s (dialog of the FMU block)', ...
                                  block, variable, value); %#ok<AGROW>
    end

    % Lines
    for k = 1:size(scenario.links, 1)
        [from, output, to, input] = scenario.links{k, :};
        source = sprintf('%s/%d', from, find(strcmp(api.outputs, output)));
        destination = sprintf('%s/%d', to, find(strcmp(api.inputs, input)));
        label = sprintf('%s.%s -> %s.%s', from, output, to, input);
        if scenario.rate_transitions && rates(from) ~= rates(to)
            transition = sprintf('RT_%s_%s_%s_%s', from, output, to, input);
            add_block(api.rate_transition_block, [model '/' transition], ...
                      'Position', [160 + 300 * k, 320 + 40 * k, 200 + 300 * k, 350 + 40 * k]);
            ratio = max(rates(from), rates(to)) / min(rates(from), rates(to));
            if abs(ratio - round(ratio)) > 1e-9
                issues = try_set(issues, [model '/' transition], api.rate_transition_deterministic, 'off');
            end
            handle = add_line(model, source, [transition '/1'], 'autorouting', 'on');
            add_line(model, [transition '/1'], destination, 'autorouting', 'on');
        else
            handle = add_line(model, source, destination, 'autorouting', 'on');
        end
        set_param(handle, 'Name', label);    % check on the model that each line joins the named ports (UNVERIFIED order)
    end

    % Root Outports for the unconnected outputs (as auto_output in the container)
    nb_outports = 0;
    for k = 1:size(scenario.blocks, 1)
        block = scenario.blocks{k, 1};
        for j = 1:numel(api.outputs)
            output = api.outputs{j};
            if any(strcmp(scenario.links(:, 1), block) & strcmp(scenario.links(:, 2), output))
                continue
            end
            nb_outports = nb_outports + 1;
            name = sprintf('%s.%s', block, output);
            add_block(api.outport_block, [model '/' name], ...
                      'Position', [260 + 300 * (k - 1), 80 + 30 * j, 290 + 300 * (k - 1), 94 + 30 * j]);
            handle = add_line(model, sprintf('%s/%d', block, j), [name '/1'], 'autorouting', 'on');
            set_param(handle, 'Name', name);
        end
    end

    save_system(model, fullfile(folder, [model '.slx']));
    close_system(model, 0);
end


function issues = try_set(issues, path, parameter, value)
    try
        set_param(path, parameter, value);
    catch err
        issues{end + 1} = sprintf('FAILED: set_param(''%s'', ''%s'', ''%s''): %s', path, parameter, value, ...
                                  err.message);
    end
end


function text = on_off(value)
    if value
        text = 'on';
    else
        text = 'off';
    end
end


function path = absolute(path)
    if ~java.io.File(path).isAbsolute()
        path = fullfile(pwd, path);
    end
end


function write_lines(filename, lines)
    file = fopen(filename, 'w');
    for k = 1:numel(lines)
        fprintf(file, '%s\n', lines{k});
    end
    fclose(file);
end
