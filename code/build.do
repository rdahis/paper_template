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

// build
	do "code/sub/build_datasets.do"

// merge
	do "code/sub/build_merge.do"

// covariates
	do "code/sub/build_covariates.do"

// compress and Save
	compress
	save "output/data/data.dta", replace

log close
