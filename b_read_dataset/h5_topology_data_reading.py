import h5py


def read_topology(loc='a_dataset/topology.h5'):
    """Read HDF5 topology file. Returns dict with 'hydro' and 'thermal' keys."""
    f = h5py.File(loc, 'r')
    dataset_index = [n for n in f.keys()]
    list_index = []
    for n in dataset_index:
        list_index += [m for m in f[n].keys()]

    HYDRO = f.get('HYDRO')
    TERM = f.get('TERM')

    data = {'hydro': {}, 'thermal': {}}

    # --- Hydro ---
    data['hydro']['modules'] = list_index[3:12]
    data['hydro']['nb_seg'] = {}

    for i in range(3, 12):
        module_id = list_index[i]
        for value in HYDRO[module_id]:
            if i == 3:
                data['hydro'][value] = {}
            try:
                if value in HYDRO['49904'].keys():
                    if value in ['P_max', 'P_min', 'Qb_max', 'Qs_max', 'V_max']:
                        data['hydro'][value][module_id] = HYDRO[module_id][value][()]
                    elif value in ['Qd_max', 'En_eq']:
                        data['hydro'][value][module_id] = [r for r in HYDRO[module_id][value][()]]
                    else:
                        data['hydro'][value][module_id] = [r for r in HYDRO[module_id][value][()]]
            except Exception:
                data['hydro'][value][module_id] = {}

        data['hydro']['nb_seg'][module_id] = [s for s in range(len(data['hydro']['En_eq'][module_id]))]

    data['hydro']['B_output']['49904'] = []
    data['hydro']['S_output']['49904'] = []

    # --- Thermal ---
    data['thermal']['generators'] = list_index[-4:]
    for i in range(1, 5):
        gen_id = list_index[-i]
        for value in TERM[gen_id].keys():
            if i == 1:
                data['thermal'][value] = {}
            try:
                data['thermal'][value][gen_id] = TERM[gen_id][value][()]
            except Exception:
                data['thermal'][value][gen_id] = 0

    f.close()
    return data


if __name__ == '__main__':
    data = read_topology()
    print('Modules:', data['hydro']['modules'])
    print('Generators:', data['thermal']['generators'])
