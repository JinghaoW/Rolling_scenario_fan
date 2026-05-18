import statistics

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler


def read_wind_profile(loc='a_dataset/wind_production_inMWh.xlsx', max_wind=50, T=0, year=5, window_size=364):
    """Read wind production, scale per-year with MinMax, return (fs_value, ss_dict)."""
    wind_data = pd.read_excel(loc, index_col=[0]).loc['2016-01-01':'2020-12-31']['Produksjon [MWh]']

    wind_scenarios = []
    for yr in range(16, 21):
        wind = wind_data['20{}-01-01'.format(yr):'20{}-12-31'.format(yr)]
        wind = wind.reset_index(drop=True)
        if len(wind) > 365:
            wind = wind[:-1]
        wind_norm = MinMaxScaler().fit_transform(wind.values.reshape(-1, 1))
        wind_scenarios.append(wind_norm.reshape(-1))

    wind_scenario_df = pd.DataFrame(wind_scenarios) * max_wind
    wind = wind_scenario_df.values.flatten()

    wind_adjusted = {'wind_fs': {}, 'wind_ss': {}}
    for i in range(year):
        wind_roll_ss = wind[i * window_size + T + 1: i * window_size + window_size + T + 1]
        wind_roll_fs = wind[i * window_size + T: i * window_size + T + 1]
        wind_adjusted['wind_fs'][i] = wind_roll_fs
        wind_adjusted['wind_ss'][i] = wind_roll_ss

    wind_adjusted['wind_fs'] = statistics.mean(
        [item for sublist in wind_adjusted['wind_fs'].values() for item in sublist]
    )

    return wind_adjusted['wind_fs'], wind_adjusted['wind_ss']


if __name__ == '__main__':
    wind_fs, wind_ss = read_wind_profile(max_wind=80, T=1)
    print(wind_fs)
    print(wind_ss, len(wind_ss[0]))
