import pandas as pd


def read_and_adjust_load(loc, area='NO1', max_load=450, T=0, window_size=364):
    """Read load from Excel, scale to max_load, return (first-stage, second-stage) DataFrames."""
    sheet_name = '{}'.format(area)
    load_data = pd.read_excel(loc, sheet_name, index_col=[0]).reset_index(drop=True)
    load_data = (load_data.values.reshape(-1, 1) / 7).repeat(7, axis=0)
    load_max = load_data.max()
    adjusted_load = load_data * max_load / load_max

    rolling_load_ss = pd.DataFrame(adjusted_load[T: T + window_size]).reset_index(drop=True)
    rolling_load_fs = pd.DataFrame(adjusted_load[T: T + 1]).reset_index(drop=True)

    return rolling_load_fs, rolling_load_ss


if __name__ == '__main__':
    loc = 'a_dataset/consumption-weekly-3years.xlsx'
    rolling_load_fs, rolling_load_ss = read_and_adjust_load(loc, area='NO1', max_load=450, T=0, window_size=364)
    print('fs', rolling_load_fs)
    print('ss', rolling_load_ss)
