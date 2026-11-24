#include "plot_common.h"

// Exchange numbers and strings with Python; keep ROOT objects in C++.
namespace {
thread_local std::string error;
}

extern "C" {
void* dqm_plot_create(const char* request) {
    try {
        error.clear();
        return new DQMPlot::Plots(request);
    } catch (const std::exception& e) {
        error = e.what();
        return nullptr;
    }
}

const char* dqm_plot_error() {
    return error.c_str();
}

void dqm_plot_destroy(void* handle) {
    delete static_cast<DQMPlot::Plots*>(handle);
}

const char* dqm_plot_call(void* handle, const char* request) {
    auto& p = *static_cast<DQMPlot::Plots*>(handle);
    try {
        auto j = DQMPlot::parse(request);
        auto op = j.get<std::string>("operation");
        if (op == "add")
            p.add(j.get<std::string>("path"));
        else if (op == "save")
            p.save(j.get<std::string>("path"), j.get<std::string>("analysis"));
        else if (op != "statistics")
            throw std::runtime_error("Unknown plot operation");
        p.response = p.statistics();
    } catch (const std::exception& e) {
        DQMPlot::Json j;
        j.put("error", e.what());
        p.response = DQMPlot::encode(j);
    }
    return p.response.c_str();
}
}
