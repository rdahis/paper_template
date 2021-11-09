//----------------------------------------------------------------------------//
//
// project: 
//
// do.file: analysis
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

log using "output/analysis.log", replace

use "output/data/data.dta", clear


//----------------------------------------------------------------------------//
// main
//----------------------------------------------------------------------------//

// tables
	do "code/sub/analysis_tables.do"

// figures
	do "code/sub/analysis_figures.do"

// regressions
	do "code/sub/analysis_regressions.do"

log close
