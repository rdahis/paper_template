//----------------------------------------------------------------------------//
//
// Paper:
//
// do.file: build
//
// Author(s):
//
//----------------------------------------------------------------------------//


//----------------------------------------------------------------------------//
// Shortcuts
//----------------------------------------------------------------------------//

global person=""

if "$person"=="" global path /path_to_paper/paper


//----------------------------------------------------------------------------//
// Preface
//----------------------------------------------------------------------------//

log using "$path/build/output/build.log"

clear all
set more off
* set graphics off
cd "$path/build"


//----------------------------------------------------------------------------//
// Main
//----------------------------------------------------------------------------//

// Build
	do "code/sub/build_datasets.do"
// Merge
	do "code/sub/build_merge.do"
// Covariates
	do "code/sub/build_covariates.do"
// Compress and Save
	compress
	save "output/data.dta", replace

log close