function api = probe_simulink_api()
%PROBE_SIMULINK_API Simulink names used by build_scenarios, in one place.
%   The names marked UNVERIFIED are not documented by MathWorks (or only by community answers): if one of them
%   is wrong on MATLAB R2024b, correct it here only. build_scenarios reports every call that failed.

    % Library path of the FMU block (Simulink Extras / FMU Import / FMU).            UNVERIFIED
    api.fmu_block = 'simulink_extras/FMU Import/FMU';
    api.fmu_library = 'simulink_extras';

    % Rate Transition block.
    api.rate_transition_block = 'simulink/Signal Attributes/Rate Transition';

    % Documented parameters of the FMU block.
    api.fmu_name = 'FMUName';                   % FMU file
    api.sample_time = 'FMUSampleTime';          % sample time (Co-Simulation)
    api.input_mapping = 'FMUInputMapping';      % 'Flat': one port per scalar input
    api.output_mapping = 'FMUOutputMapping';    % 'Flat': one port per scalar output
    api.flat = 'Flat';

    % Ports of the probe with the 'Flat' mappings, in the order of modelDescription.xml.   UNVERIFIED
    api.inputs = {'u_cont', 'u_disc', 'u_int', 'u_bool'};
    api.outputs = {'y_cont', 'y_disc', 'y_int', 'y_bool', 'y_init', 'y_time'};

    % Value of an FMU parameter: set_param(block, <variable name>, <MATLAB expression>)    UNVERIFIED
    % (MATLAB Answers 2128526). The start value of an input has no known programmatic name: set by hand.
    api.parameter_name = @(variable) variable;

    % Model configuration (documented).
    api.solver = {'SolverType', 'Fixed-step', 'Solver', 'FixedStepDiscrete', 'FixedStep', '0.01'};
    api.multitasking = 'EnableMultiTasking';
end
