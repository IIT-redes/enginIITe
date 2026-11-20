# SB72 input package

Input data of the SB72 study case: one network, twelve snapshots and one set of flexibility service providers. It is run with `config/config_SB72.yaml`. The folder `market_inputs/` is created by the runs (sensitivity matrices) and is not part of the package.

## Network
- SimBench `1-MV-comm--0-sw` (SimBench package profiles of 2016), both 110/20 kV transformers at 40 MVA (vk 16.2 %, as SimBench); no line rating, impedance or topology change.
- New-connection (NFD) units: per role feeder a V group on downstream buses (sets the voltage) and a C group on middle / upstream buses behind the head line (sets the congestion). NFD generators run at zero reactive power, NFD loads at power factor 0.95. NFD units never take part in the market.
- Some batteries are installed idle (p = q = 0) in the network; the FSP files list the batteries that bid.

## Operating backgrounds (every native element follows its own SimBench profile at the timestamp)
- DER: Saturday 16 Apr 2016 12:00: sunny and windy noon, weekend demand; 110 kV supply voltage 1.020 pu (transformer tap fixed).
- LOAD: Wednesday 27 Jan 2016 17:45: winter evening peak, no PV, low wind; 110 kV supply voltage 0.990 pu (transformer tap fixed).
- MIX: Tuesday 26 Jul 2016 12:45: sunny, windy weekday noon with business demand; 110 kV supply voltage 0.995 pu (transformer tap fixed).
- Customer types are the SimBench profile names: MV customers G0-G6 (BDEW commercial standard profiles: G0 general commercial, G1 offices / public buildings (weekday 8-18 h), G2 evening business, G3 continuous operation (industrial-like), G4 shops / retail, G5 bakery, G6 weekend business); LV grids lv_urban6 / lv_semiurb4-5 (urban) and lv_rural1-3 (rural) are equivalent LV networks with their rooftop PV (lv_RES) modelled separately.
- The supply voltage per snapshot is in `profile/profile_ext_grid_vm.xlsx` and is read through `network.ext_grid_profile` in the configuration.

## Feeder roles
- Export (over-voltage, reverse-flow congestion): F02, the wind feeder (localized), F02 + F03 (widespread).
- Import (under-voltage, import congestion): F07, the largest load feeder (localized), F07 + F09 (widespread).
- MIX combines the same roles. The first feeder carries the severity of the snapshot; the second feeder of a widespread snapshot carries the next milder severity.

## Snapshots (pre-market AC power flow, limits 0.95-1.05 pu and 100 %)

| S | scenario | HV pu | Vmax | Vmin | max loading % | buses over/under | lines > 100 % | feeder loading |
|---|---|---|---|---|---|---|---|---|
| 1 | DER_LOC_LOW | 1.020 | 1.0610 | 1.0190 | 104.9 | 7/0 | 1 | F02:104.9 |
| 2 | DER_LOC_HIGH | 1.020 | 1.0690 | 1.0189 | 110.2 | 8/0 | 1 | F02:110.2 |
| 3 | DER_WID_LOW | 1.020 | 1.0607 | 1.0187 | 105.2 | 13/0 | 2 | F02:105.2 F03:101.2 |
| 4 | DER_WID_HIGH | 1.020 | 1.0690 | 1.0185 | 110.2 | 15/0 | 3 | F02:110.2 F03:105.0 |
| 5 | LOAD_LOC_LOW | 0.990 | 0.9768 | 0.9400 | 105.3 | 0/11 | 3 | F07:105.3 |
| 6 | LOAD_LOC_HIGH | 0.990 | 0.9763 | 0.9335 | 110.2 | 0/13 | 3 | F07:110.2 |
| 7 | LOAD_WID_LOW | 0.990 | 0.9702 | 0.9400 | 105.2 | 0/28 | 5 | F07:105.2 F09:102.0 |
| 8 | LOAD_WID_HIGH | 0.990 | 0.9694 | 0.9335 | 110.2 | 0/30 | 6 | F07:110.3 F09:105.0 |
| 9 | MIX_LOC_LOW | 0.995 | 1.0570 | 0.9430 | 104.5 | 5/9 | 4 | F02:104.5 F07:104.5 |
| 10 | MIX_LOC_HIGH | 0.995 | 1.0615 | 0.9410 | 108.8 | 6/10 | 6 | F02:108.8 F07:108.8 |
| 11 | MIX_WID_LOW | 0.995 | 1.0557 | 0.9433 | 104.5 | 4/16 | 10 | F02:104.5 F03:103.0 F07:103.9 F09:100.8 |
| 12 | MIX_WID_HIGH | 0.995 | 1.0586 | 0.9405 | 108.9 | 5/19 | 11 | F02:108.9 F03:105.0 F07:108.0 F09:102.9 |

Calibration windows (primary feeder): DER LOW: 1.055-1.061 pu, 104.5-106 %; DER HIGH: 1.066-1.072 pu, 109.5-111 %; LOAD LOW: 0.937-0.943 pu, 104.5-106 %; LOAD HIGH: 0.931-0.936 pu, 109.5-111 %; MIX LOW: <= 1.060 / >= 0.940 pu, 103.5-105.5 %; MIX HIGH: <= 1.065 / >= 0.939 pu, 108-109.5 %.
Second feeder of widespread snapshots: DER LOW: 1.051-1.056 pu, 100.6-101.8 %; DER HIGH: 1.055-1.062 pu, 104-106 %; LOAD LOW: 0.944-0.949 pu, 101-103 %; LOAD HIGH: 0.938-0.944 pu, 104-106 %; MIX LOW: <= 1.055 / >= 0.945 pu, <= 103 %; MIX HIGH: <= 1.060 / >= 0.940 pu, <= 106 %.
MIX WID HIGH (S12) congests all four role feeders, each at least as much as MIX WID LOW (S11): F02 108-109.5 %, F03 104-106 %, F07 106-108 % and 0.939-0.943 pu, F09 102-104.5 % and 0.944-0.9475 pu.

## Flexibility service providers (one provider per resource)
- Depth F0k: loads k x 0.05 of their power (initial_value bidding); generators k x 0.33 of their remaining technical headroom (headroom_value bidding: 33, 66 and 99 % at F01-F03); batteries k/6 of their rating (mva_value bidding). Offers are clipped by the platform to headroom, MVA and state of charge.
- Providers: MV customers >= 0.35 MW, every MV generator, batteries of the hybrid PV / wind plants >= 0.25 MW (0.6 MW per MW), the existing 1.0 MW feeder battery of the downstream half of the export feeders F02 and F03, one aggregator on the urban / semi-urban LV grids (demand and rooftop PV).
- No home batteries and no battery below 0.1 MW; the providers, their owners and technologies are listed in `fsp_files/FSPOwnership.csv`.

| providers | owners | loads | generators | batteries | battery MW |
|---|---|---|---|---|---|
| 153 | 23 | 74 | 73 | 6 | 7.19 |
