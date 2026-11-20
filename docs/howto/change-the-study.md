# Change the study

This page lists the keys of the configuration file to edit for the usual goals. Each key is described in the [configuration reference](../reference/configuration.md), and the comment above it in the example file says what it does and which values it takes. For the first preparation of a study, see [Prepare your own study](../tutorial/build-your-study.md).

| I want to | Change these keys |
|---|---|
| Study one day hour by hour | `simulation_window: [0, 24]`, `simulation_window_as_timesteps: True`, `consecutive_hours: 24` |
| Study independent scenarios | `simulation_window_as_timesteps: False`, `consecutive_hours: 1`, `intertemp_cons: False` |
| Let batteries carry their charge between hours | `intertemp_cons: True`, with `simulation_window_as_timesteps: True` |
| Solve congestion only | `ModelTAG: 'CM'` |
| Solve voltage only | `ModelTAG: 'VC'` |
| Compare the three products | `ProductTAG: ['P', 'Q', 'PQ']` |
| Compare bid depths | `FspTAG: ['F01', 'F02', 'F03']` |
| Test larger batteries | `StorageTag: 'SK02'` |
| Remove the batteries from the market | `StorageTag: ''` |
| Use a stricter voltage band | `VLTAG: ['VL05']` |
| Stress the network with more load | `scen_factor_load: 1.2` |
| Make a quick test run | `FspTAG: ['F01']` |
| Run again after changing the inputs | `force_HVM: True`, `force_HCM: True`, and a new `simulation_tag` |
| Keep the results of two runs | A different `simulation_tag` in each |

## Things to keep in mind

- The three keys `simulation_window_as_timesteps`, `consecutive_hours` and `intertemp_cons` work together and must agree. Independent scenarios need `consecutive_hours: 1` and `intertemp_cons: False`.
- The window `simulation_window: [first, last + 1]` selects rows of the profile files, counted from 0. `[0, 24]` is rows 0 to 23, and `[0, 8760]` is a year of hourly rows.
- If the chosen `ModelTAG` finds no violation in the window, the platform prints a warning and ends the run. See [Common problems](common-problems.md#messages-during-a-run).
- A new run with the same `simulation_tag` overwrites the old result folder.
