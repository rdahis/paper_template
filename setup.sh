#!/bin/bash

NON_VERSIONED_PATH=""
REPO_PATH=""

cd $REPO_PATH

ln -s "${NON_VERSIONED_PATH}/input" input
ln -s "${NON_VERSIONED_PATH}/output/data" output/data
ln -s "${NON_VERSIONED_PATH}/output/logs" output/logs
ln -s "${NON_VERSIONED_PATH}/tmp" tmp

