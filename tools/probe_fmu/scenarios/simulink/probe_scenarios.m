function scenarios = probe_scenarios()
%PROBE_SCENARIOS Definition of the Simulink side of the comparison scenarios.
%   Same assemblies as the FMU Container descriptions (../S*.json), see ../README.md and
%   docs/local/importer_comparison.md (section "Study scenarios").
%
%   Each scenario is a struct:
%     name          model name (S1, S2, S3, S4s, S4m, S5, S6s, S6m)
%     blocks        {block name, probe model} rows (probe model: Probe10ms, Probe20ms, Probe50ms)
%     links         {from block, output, to block, input} rows
%     parameters    {block, parameter, MATLAB expression} rows (trace_file is added for every block)
%     input_starts  {block, input, value} rows: start values of inputs (set by hand if the API does not allow it)
%     multitasking  true: "Treat each discrete rate as a separate task"
%     rate_transitions  true: a Rate Transition block on each link between different rates
%     stop_time     stop time (s)

    abc10 = {'A', 'Probe10ms'; 'B', 'Probe10ms'; 'C', 'Probe10ms'};
    rates = {'A', 'Probe10ms'; 'B', 'Probe20ms'; 'C', 'Probe50ms'};
    links4 = {'A', 'y_time', 'B', 'u_cont';
              'A', 'y_int',  'B', 'u_int';
              'B', 'y_time', 'C', 'u_cont';
              'C', 'y_time', 'A', 'u_disc';
              'C', 'y_int',  'A', 'u_int'};
    links5 = {'A', 'y_time', 'B', 'u_cont';
              'B', 'y_cont', 'C', 'u_cont';
              'A', 'y_time', 'B', 'u_disc';
              'B', 'y_disc', 'C', 'u_disc'};
    compute = {'A', 'compute_time', '0.005'; 'B', 'compute_time', '0.005'; 'C', 'compute_time', '0.005';
               'A', 'compute_sleep', 'off'; 'B', 'compute_sleep', 'off'; 'C', 'compute_sleep', 'off'};
    none = cell(0, 3);
    no_links = cell(0, 4);

    scenarios = [ ...
        scenario('S1', {'A', 'Probe10ms'}, no_links, none, none, false, false, 0.2), ...
        scenario('S2', {'A', 'Probe10ms'}, no_links, ...
                 {'A', 'p_real', '3'; 'A', 'p_tunable', '0.5'; 'A', 'compute_time', '0'}, ...
                 {'A', 'u_cont', '2'; 'A', 'u_disc', '4'; 'A', 'u_int', '7'; 'A', 'u_bool', 'true'}, ...
                 false, false, 0.2), ...
        scenario('S3', abc10, {'A', 'y_init', 'B', 'u_cont'; 'B', 'y_cont', 'C', 'u_cont'}, ...
                 {'A', 'p_real', '3'; 'C', 'p_real', '2'}, {'A', 'u_cont', '2'}, false, false, 0.2), ...
        scenario('S4s', rates, links4, none, none, false, false, 0.2), ...
        scenario('S4m', rates, links4, none, none, true, true, 0.2), ...
        scenario('S5', abc10, links5, none, none, false, false, 0.2), ...
        scenario('S6s', abc10, no_links, compute, none, false, false, 1.0), ...
        scenario('S6m', abc10, no_links, compute, none, true, false, 1.0)];
end


function s = scenario(name, blocks, links, parameters, input_starts, multitasking, rate_transitions, stop_time)
    trace = cell(size(blocks, 1), 3);
    for k = 1:size(blocks, 1)
        trace(k, :) = {blocks{k, 1}, 'trace_file', sprintf('''%s.csv''', blocks{k, 1})};
    end
    s = struct('name', name, 'blocks', {blocks}, 'links', {links}, 'parameters', {[trace; parameters]}, ...
               'input_starts', {input_starts}, 'multitasking', multitasking, ...
               'rate_transitions', rate_transitions, 'stop_time', stop_time);
end
