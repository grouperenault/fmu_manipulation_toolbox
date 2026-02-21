# Container with LS-BUS enable FMUs

![Container with LS-BUS](ls-bus-container.png)


## Step-by-step example

The topology supported be `fmucontainer` require a BUS Simulation FMU. (See 3.2.2 of LS-BUS specification).

1. From [LS-BUS Examples](https://github.com/modelica/fmi-ls-bus-examples) build 2 nodes 
[`node1.fmu`](https://github.com/grouperenault/fmu_manipulation_toolbox/raw/refs/heads/main/tests/ls-bus/node1.fmu) and
[`node2.fmu`](https://github.com/grouperenault/fmu_manipulation_toolbox/raw/refs/heads/main/tests/ls-bus/node2.fmu))
and the Bus Simulation 
[`bus.fmu`](https://github.com/grouperenault/fmu_manipulation_toolbox/raw/refs/heads/main/tests/ls-bus/bus.fmu).

2. Create a `bus+nodes.json` file describing the container. In this example, it 
connects `node1.fmu` to `bus.fmu` through their terminals and the same for `node2.fmu`.
   ```json
       {
         "name": "bus+nodes.fmu",
         "fmu": [
           "bus.fmu",
           "node1.fmu",
           "node2.fmu"
         ],
         "link": [
           [ "node1.fmu", "CanChannel", "bus.fmu", "Node1"],
           [ "node2.fmu", "CanChannel", "bus.fmu", "Node2"]
         ],
         "step_size": 0.1
       }
   ```

3. Create the container with the following command line
   ```
   fmucontainer -container bus+nodes.json -fmi 3
   ```

4. You could run the `bus+nodes.fmu` with you're favourite FMI-importer. Here is a 
    ```python
    from fmpy.simulation import simulate_fmu
    
    def log(*args):
        msg = args[-1]
        if isinstance(args[-1], bytes):
            msg = msg.decode('utf-8')
        print(f"{msg}")
    
    
    simulate_fmu("bus+node.fmu", step_size=0.1, stop_time=1,
                 output_interval=0.1, validate=True, use_event_mode=True,
                 logger=log, debug_logging=True, relative_tolerance=1e-6)
    ```
