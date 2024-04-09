{
    package Debian::Debhelper::Sequence::kf6;
    use Debian::Debhelper::Dh_Version;
    use Debian::Debhelper::Dh_Lib qw(error);

    1;
}

# Build with KF6 buildsystem by default
add_command_options("dh_auto_configure", "--buildsystem=kf6");
add_command_options("dh_auto_build", "--buildsystem=kf6");
add_command_options("dh_auto_test", "--buildsystem=kf6");
add_command_options("dh_auto_install", "--buildsystem=kf6");
add_command_options("dh_auto_clean", "--buildsystem=kf6");

# Exclude KF6 documentation from dh_compress by default
add_command_options("dh_compress",
    qw(-X.dcl -X.docbook -X-license -X.tag -X.sty -X.el));

1;
