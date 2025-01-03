#!/bin/sh

set -eux

dirs='
    add_int64_t_subst
    add_time_t_subst
    change_int64_t_subst_to_time_t
    change_time_t_subst_to_int64_t
    missing_in_new_version
    missing_on_new_arch
    new_symbols
'

export PATH=$(pwd):$PATH
export PERLLIB=$(pwd)/perllib

for dir in $dirs; do
    cd $dir
    cp debian/libfoo1.symbols.before debian/libfoo1.symbols
    pkgkde-symbolshelper batchpatch -v 1.0 *.diff
    diff -uN debian/libfoo1.symbols.expected debian/libfoo1.symbols
    rm debian/libfoo1.symbols
    cd ..
done
