project(SymbolsHelper_tests)
file(COPY run_tests.sh
     ../../pkgkde-symbolshelper
     ../../perllib
     add_int64_t_subst
     add_time_t_subst
     change_int64_t_subst_to_time_t
     change_time_t_subst_to_int64_t
     missing_in_new_version
     missing_on_new_arch
     new_symbols
     DESTINATION .
)
add_test(NAME symbolshelper COMMAND run_tests.sh)
