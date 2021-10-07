
from subprocess import call
import platform
import shutil, os

system = platform.system()

person = ''     # use the person variable to keep paths in order with multiple machines being used

if person == '':
    path = '/path/to/main_paper'
    dataSources = ['/path/to/data_sources/data_set_1',
                   '/path/to/data_sources/data_set_2']   # list of data sets used as input to paper

if system == 'Windows':
	pass

else:
	# Clears Input
	folder = '/input'
	shutil.rmtree(path+folder)
	os.mkdir(path+folder)

	# Copies Data
    for file in dataSources:
        call(['cp', file, path+'/input'])
