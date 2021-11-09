
from subprocess import call
import platform

system = platform.system()

person = ''     # use the person variable to keep paths in order with multiple machines being used

if person == '':
	path = '/path/to/main_paper'

if system == 'Windows':
	pass

else:
    print "Cleans Output and Temporary"
    for folder in ['/output', '/tmp']:
        shutil.rmtree(path+folder)
        os.mkdir(path+folder)
        
    print "//-- Gets Input --//"
    call(['python', path+'/code/get_input.py'])

    print "//-- Runs Build --//"
    call(['stata', '-b', 'do' + '\"' + path+'/code/build.do'+'\" &'])
    for file in glob.glob(path+'/*.log'):
        os.remove(file)
    
    print "//-- Runs Analysis --//"
    call(['stata', '-b', 'do' + '\"' + path+'/code/analysis.do'+'\" &'])
    for file in glob.glob(path+'/*.log'):
        os.remove(file)
    
	print "//-- Compiles TeX --//"
	call(['latexmk', path+'/products/paper/main_article.tex')

	print "Congratulations, you have a shiny new paper!"





