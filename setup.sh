#!/bin/bash

NON_VERSIONED_PATH=""
REPO_PATH=""

ln -shF "${NON_VERSIONED_PATH}/input"       "${REPO_PATH}/input"
ln -shF "${NON_VERSIONED_PATH}/output/data" "${REPO_PATH}/output/data"
ln -shF "${NON_VERSIONED_PATH}/output/logs" "${REPO_PATH}/output/logs"
ln -shF "${NON_VERSIONED_PATH}/tmp"         "${REPO_PATH}/tmp"
