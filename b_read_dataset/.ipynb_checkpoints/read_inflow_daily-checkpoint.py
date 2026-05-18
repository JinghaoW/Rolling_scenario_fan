import pandas as pd
import numpy as np
import os

# Resolution is Mm3/week, convert to m3/s
os.chdir('/cluster/home/jinghaow/SFP_data_with_wind')


def process_data(loc, factor, tot_years, window_size, T, start_year=0):
    data = pd.read_csv(loc, sep=',', index_col=[0]) * factor

    inflow = {}
    inflow_int = {}
    for year in range(start_year, start_year + tot_years):
        inflow[year-start_year+1] = {}
        inflow_int[year-start_year+1] = {}
        for i in range(49904, 49913):
            data_dayly = (data[str(i)].values.reshape(-1, 1) / 1).repeat(7, axis=0)  ## Mm^3/week
            data_1 = data_dayly[year * window_size + T + 1: year * window_size + T + window_size + 1] * (
                        10 ** 6 / (7 * 24 * 60 * 60))  ## mM3/week-->m^3/s
            data_2 = data_dayly[year * window_size + T: year * window_size + T + 1] * (
                        10 ** 6 / (7 * 24 * 60 * 60))  ## mM3/week-->m^3/s
            inflow[year-start_year+1][str(i)] = pd.DataFrame(data_1).reset_index(drop=True).values.flatten()
            inflow_int[year-start_year+1][str(i)] = pd.DataFrame(data_2).reset_index(drop=True).values.flatten()
    inflow_int = {key: np.mean([value[key] for value in inflow_int.values()]) for key in inflow_int[year-start_year+1]}
    return inflow, inflow_int


def read_inflow(factor: int, loc_re, loc_un, tot_years, window_size, T, start_year=0):
    inflow = {}
    inflow_int = {}
    inflow['regulated'], inflow_int['regulated'] = process_data(loc_re, factor, tot_years, window_size, T, start_year)
    inflow['unregulated'], inflow_int['unregulated'] = process_data(loc_un, factor, tot_years, window_size, T,
                                                                    start_year)
    return inflow, inflow_int


if __name__ == '__main__':
    loc_re = '0dataset/regulated_inflow_newscen.csv'
    loc_un = '0dataset/unregulated_inflow_newscen.csv'

    inflow, inflow_int = read_inflow(1, loc_re, loc_un, 10, 365, 0, 2999)
    print(inflow_int['regulated'])
