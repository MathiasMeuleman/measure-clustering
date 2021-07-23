import json
import time
from itertools import product
from os import walk
from os.path import dirname, join, realpath

from gamera.core import load_image, init_gamera, ONEBIT
from gamera.toolkits.musicstaves.plugins.evaluation import segment_error, interruption_error
from gamera.toolkits.musicstaves.musicstaves_linetracking import MusicStaves_linetracking
from gamera.toolkits.musicstaves.musicstaves_rl_roach_tatem import MusicStaves_rl_roach_tatem
from gamera.toolkits.musicstaves.musicstaves_skeleton import MusicStaves_skeleton
from gamera.toolkits.musicstaves.stafffinder_dalitz import StaffFinder_dalitz
from gamera.toolkits.musicstaves.stafffinder_meuleman import StaffFinder_meuleman

img_switch = False
deform_switch = False
alg_switch = True
staff_switch = False
error_switch = False

# -----------------
# Input images
# -----------------
test_dir = join(dirname(dirname(dirname(realpath(__file__)))), 'OMR-measure-segmenter-data/testset')
if img_switch:
    test_cats = ['historic', 'modern', 'tablature']
    input_images = []
    for cat in test_cats:
        (cur_dir, _, filenames) = walk(join(test_dir, cat)).next()
        images = [f for f in filenames if f.endswith('.png') and not 'nostaff' in f]
        for img in images:
            base_name = '.'.join(img.split('.')[0:-1])
            input_images.append((join(cat, base_name + '.png'), join(cat, base_name + '-nostaff.png')))
else:
    input_images = [('modern/diabelli.png', 'modern/diabelli-nostaff.png')]

# ------------------
# Deformation methods
# ------------------
if deform_switch:
    deformations = {
        'no-deform': {},
        'rotation': {'angle': range(-18, 19)},
        'curvature': {'ampx': [x * 0.02 for x in range(1, 16)]},
        'typeset_emulation': {'n_gap': range(1, 13), 'n_shift': range(1, 11), 'p_gap': [0.5]},
        'staffline_interruptions': {'alpha': [x * 0.01 for x in range(1, 11)], 'n': range(1, 11), 'p': [0.5]},
        'staffline_thickness_variation': {'c': [x * 0.05 for x in range(10, 20)], 'min': [1], 'max': range(2, 11)},
        'staffline_y_variation': {'c': [x * 0.05 for x in range(10, 20)], 'maxdiff': range(2, 11)},
        'degrade_kanungo_parallel': {'eta': [0], 'k': [2], 'a0': [0.5, 1], 'a': [x * 0.25 for x in range(1, 7)], 'b0': [0.5, 1], 'b': [x * 0.25 for x in range(1, 7)]},
        'white_speckles_parallel': {'k': [2], 'n': [10], 'p': [x * 0.01 for x in range(1, 51)]},
    }
else:
    deformations = {
        # 'rotation': {'angle': range(-18, 18, 9)},
        'no-deform': {},
    }

deformation_sets = {}
for k, v in deformations.iteritems():
    keys = list(v.keys())
    cartesian = list(product(*list(v.values())))
    sets = [dict(zip(keys, c)) for c in cartesian]
    deformation_sets[k] = sets

# --------------------
# Removal algorithms
# --------------------
if alg_switch:
    algorithms = [
        {'name': 'linetracking_height', 'method': MusicStaves_linetracking, 'args': {'symbol_criterion': 'runlength'}},
        {'name': 'linetracking_chord', 'method': MusicStaves_linetracking, 'args': {'symbol_criterion': 'secondchord'}},
        {'name': 'roach_tatem_original', 'method': MusicStaves_rl_roach_tatem, 'args': {'postprocessing': False}},
        {'name': 'roach_tatem_improved', 'method': MusicStaves_rl_roach_tatem, 'args': {'postprocessing': True}},
        {'name': 'skeletonization', 'method': MusicStaves_skeleton, 'args': {}},
    ]
else:
    algorithms = [
        {'name': 'linetracking_height', 'method': MusicStaves_linetracking, 'args': {'symbol_criterion': 'runlength'}},
    ]

# --------------------
# Staff Finders
# --------------------
if staff_switch:
    staff_finders = [
        {'name': 'Dalitz', 'method': StaffFinder_dalitz},
        {'name': 'Meuleman', 'method': StaffFinder_meuleman}
    ]
else:
    staff_finders = [
        {'name': 'Dalitz', 'method': StaffFinder_dalitz},
    ]

# --------------------
# Error metrics
# --------------------
if error_switch:
    error_metrics = [
        'pixel',
        'segmentation',
        'interruption'
    ]
else:
    error_metrics = ['pixel']


def get_num_lines_arg(staff_finder_name, infile):
    if staff_finder_name == 'Meuleman':
        return 0
    if infile.startswith('tablature'):
        return 6
    if infile.startswith('historic') and 'gregorian' in infile:
        return 4
    return 5


def deform_image(image, image_staff_only, method, params):
    if method == 'no-deform':
        return image.rotation(im_staffonly=image_staff_only, angle=0)
    args = params.copy()
    args['im_staffonly'] = image_staff_only
    return getattr(image, method)(**args)


def apply_error_metric(image, Gstaves, Sstaves, skel_list, metric):
    if metric == 'pixel':
        result = list(image.pixel_error(Gstaves, Sstaves))
        keys = ['error', 'e1', 'e2', 'a']
        return dict(zip(keys, result))
    if metric == 'segmentation':
        result = list(segment_error(Gstaves, Sstaves))
        result.append(float(sum(result) - result[0]) / float(sum(result)))
        keys = ['n1', 'n2', 'n3', 'n4', 'n5', 'n6', 'error']
        return dict(zip(keys, result))
    if metric == 'interruption':
        result = list(interruption_error(Gstaves, Sstaves, skel_list))
        result.append(float(min(result[2], result[0] + result[1])) / float(result[2]))
        keys = ['n1', 'n2', 'n3', 'error']
        return dict(zip(keys, result))


init_gamera()
results = []
for (infile, nostaves_infile) in input_images:
    for method in deformation_sets.keys():
        for params in deformation_sets[method]:
            print('Deforming ' + infile + ' with params ' + str(params) + '...')
            image = load_image(join(test_dir, infile))
            nostaves = load_image(join(test_dir, nostaves_infile))
            if image.data.pixel_type != ONEBIT:
                image = image.to_onebit()
            if nostaves.data.pixel_type != ONEBIT:
                nostaves = nostaves.to_onebit()
            image_staff_only = image.subtract_images(nostaves)
            [deformed_img, deformed_staffs, skel_list] = deform_image(image, image_staff_only, method, params)
            for removal_algorithm in algorithms:
                for staff_finder in staff_finders:
                    # deformed_img.save_PNG('_'.join([infile, method, str(params), removal_algorithm['name'], staff_finder['name']]) + '.png')
                    print('\tStaff removal alg ' + removal_algorithm['name'] + ' with ' + staff_finder['name'] + '...')
                    start = time.clock()
                    ms = removal_algorithm['method'](deformed_img, stafffinder=staff_finder['method'])
                    args = removal_algorithm['args']
                    args['num_lines'] = get_num_lines_arg(staff_finder['name'], infile)
                    ms.remove_staves(**args)
                    Gstaves = deformed_staffs
                    Sstaves = deformed_img.subtract_images(ms.image)
                    end = time.clock()
                    for metric in error_metrics:
                        error = apply_error_metric(deformed_img, Gstaves, Sstaves, skel_list, metric)

                        result = {
                            'infile': infile,
                            'nostaves': nostaves_infile,
                            'deformation': method,
                            'algorithm': removal_algorithm['name'],
                            'staff_finder': staff_finder['name'],
                            'metric': metric,
                            'error': error,
                            'time': end - start,
                        }
                        for k, v in params.iteritems():
                            result[k] = v
                        results.append(result)
                        print(result)

with open(join(test_dir, 'evaluation_results.json'), 'w') as file:
    file.write(json.dumps({'results': results}, indent=2, sort_keys=True))
