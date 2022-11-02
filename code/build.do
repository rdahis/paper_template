//----------------------------------------------------------------------------//
//
// project:
//
// do.file: build
//
// author(s):
//
//----------------------------------------------------------------------------//


//----------------------------------------------------------------------------//
// preface
//----------------------------------------------------------------------------//

clear all
clear programs
set more off
set varabbrev off
cap log close

if "c(username)" == "ricardodahis" global path /path/to/main_paper	// c(username) is your computer's username

cd "$path"

log using "output/build.log", replace


//----------------------------------------------------------------------------//
// main
//----------------------------------------------------------------------------//

// clean input files
	do "code/sub/build_clean_input_files.do"

// assemble data at <observation_level>
	do "code/sub/build_assemble_<observation_level>.do"

log close
