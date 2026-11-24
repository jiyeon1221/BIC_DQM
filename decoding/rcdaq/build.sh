#!/usr/bin/env bash
# Maintainer's 2026-11-21 instructions: RCDAQ (Autotools), then online_distribution (CMake).
set -eo pipefail
build_base="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${build_base}/setup.sh"
deps_root="${RCDAQ_DEPS_ROOT:-${build_base}/deps/sysroot}"
# CMake discovers system libraries unless a local dependency bundle is available.
dependency_flags=()
if [[ -f ${deps_root}/usr/lib64/liblzo2.so && -f ${deps_root}/usr/lib64/libbz2.so ]]; then
    dependency_flags+=(
        "-DLZO_INCLUDE_DIR=${deps_root}/usr/include"
        "-DLZO_LIBRARY=${deps_root}/usr/lib64/liblzo2.so"
        "-DBZIP2_INCLUDE_DIR=${deps_root}/usr/include"
        "-DBZIP2_LIBRARY_RELEASE=${deps_root}/usr/lib64/libbz2.so"
    )
fi
export CPPFLAGS="-I${deps_root}/usr/include -I${deps_root}/usr/include/tirpc ${CPPFLAGS:-}"
export LDFLAGS="-L${deps_root}/lib64 -Wl,-rpath,${deps_root}/lib64 -L${deps_root}/usr/lib64 -Wl,-rpath,${deps_root}/usr/lib64 -L${ONLINE_MAIN}/lib -Wl,-rpath,${ONLINE_MAIN}/lib ${LDFLAGS:-}"
# Keep transient build files and logs out of the installed tree.
build_work=$(mktemp -d /tmp/rcdaq-build.XXXXXX)
trap 'if [ $? -eq 0 ]; then rm -rf -- "$build_work"; else echo "Build files/logs retained: $build_work" >&2; fi' EXIT
mkdir -p "${build_work}/rcdaq"
cp -a "${build_base}/src/rcdaq" "${build_work}/rcdaq-source"
(
    cd "${build_work}/rcdaq"
    "${build_work}/rcdaq-source/autogen.sh" --prefix="${ONLINE_MAIN}"
    make -j"${JOBS:-4}" RPC_LDD=-ltirpc
    make install RPC_LDD=-ltirpc
) > "${build_work}/rcdaq.log" 2>&1 || { tail -n 60 "${build_work}/rcdaq.log"; exit 1; }
echo "Installed rcdaq"
cmake -S "${build_base}/src/online_distribution" -B "${build_work}/online_distribution" \
    -DCMAKE_INSTALL_PREFIX="${ONLINE_MAIN}" -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_PREFIX_PATH="${deps_root}/usr;${deps_root}" \
    -DCMAKE_INSTALL_RPATH="${ONLINE_MAIN}/lib;${deps_root}/usr/lib64;${deps_root}/lib64" \
    -DCMAKE_INSTALL_RPATH_USE_LINK_PATH=ON \
    "${dependency_flags[@]}" \
    > "${build_work}/online_distribution.log" 2>&1 || { tail -n 60 "${build_work}/online_distribution.log"; exit 1; }
cmake --build "${build_work}/online_distribution" -j"${JOBS:-4}" >> "${build_work}/online_distribution.log" 2>&1 || {
    tail -n 60 "${build_work}/online_distribution.log"; exit 1;
}
cmake --install "${build_work}/online_distribution" >> "${build_work}/online_distribution.log" 2>&1
echo "Installed eventlibraries and pmonitor (CMake)"
