#include "plot_common.h"
#include <boost/property_tree/json_parser.hpp>
#include <sstream>
#include <stdexcept>

namespace DQMPlot {
Json parse(const std::string& text) {
    Json j;
    std::istringstream in(text);
    boost::property_tree::read_json(in, j);
    return j;
}

std::string encode(const Json& j) {
    std::ostringstream out;
    boost::property_tree::write_json(out, j, false);
    return out.str();
}

std::string histogramName(const Plots& p, const std::string& name, const std::string& metric) {
    return "h_" + name + "_" + metric + "_" + p.revision;
}

std::string metricFor(const Job& j, const std::string& fallback) {
    static const std::map<std::string, std::string> m = {
        {"draw_avg", "Avg"},           {"draw_overlay", "Overlay"},
        {"draw_peakADC", "PeakADC"},   {"draw_intADC", "IntADC"},
        {"draw_toa", "TOA"},           {"draw_tot", "TOT"},
        {"draw_waveform", "Waveform"}, {"draw_singleWaveform", "Waveform"}};
    auto i = m.find(j.executable);
    return i == m.end() ? fallback : i->second;
}

Plots::Plots(const std::string& request) {
    auto j = parse(request);
    config = j.get_child("config");
    analysis = j.get_child("analysis");
    matching = config.get<bool>("matching", true);
    method = analysis.get<std::string>("method");
    type = analysis.get<std::string>("type");
    revision = analysis.get<std::string>("revision");
    limit = analysis.get<long long>("count");
    first = analysis.get<long long>("first", 0);
    for (auto& item : config.get_child("mapping")) {
        auto& e = item.second;
        auto name = e.get<std::string>("name");
        index[name] = rows.size();
        auto module = e.get<std::string>("module", name.substr(0, name.find('_')));
        rows.push_back({name, e.get<std::string>("daq"), module, e.get<int>("det"),
                        e.get<int>("side"), e.get<int>("z"), e.get<int>("y")});
    }
    if (!matching && !analysis.get_child("cuts").empty())
        throw std::runtime_error("AUX cuts require matched events; start a new session");
    for (auto& item : analysis.get_child("jobs")) {
        auto& e = item.second;
        Job job;
        job.executable = e.get<std::string>("executable");
        job.requiresMatching = e.get<bool>("requires_matching", false);
        if (!matching && job.requiresMatching)
            throw std::runtime_error(
                "This plot needs same-event channels; Execute a matched session");
        for (auto& name : e.get_child("channels")) {
            index.at(name.second.data());
            job.channels.push_back(name.second.data());
        }
        jobs.push_back(job);
    }
    sums.resize(rows.size());
    counts.resize(rows.size());
    gROOT->SetBatch(true);
    gStyle->SetOptStat(1111);
    gStyle->SetPalette(57);
}

// Delegate histogram creation to each C++ plot implementation.
TH1* Plots::hist(const std::string& name, const std::string& metric, int samples) {
    Key key{name, metric};
    auto i = hists.find(key);
    if (i != hists.end()) {
        if (samples && emptyWaveHists.erase(key))
            hists.erase(i);
        else
            return i->second.get();
    }
    TH1* h = nullptr;
    if (metric == "IntADC")
        h = make_int_adc(*this, name);
    else if (metric == "PeakADC")
        h = make_peak_adc(*this, name);
    else if (metric == "Avg")
        h = make_avg(*this, name, samples);
    else if (metric == "Overlay")
        h = make_overlay(*this, name, samples);
    else if (metric == "TOA" || metric == "TOT")
        h = make_toa_tot(*this, name, metric);
    else
        throw std::runtime_error("Unsupported histogram: " + metric);
    h->SetDirectory(nullptr);
    hists[key].reset(h);
    if (!samples && (metric == "Avg" || metric == "Overlay"))
        emptyWaveHists.insert(key);
    return h;
}

// Group by detector and side, then label the height layer or module.
std::vector<std::pair<std::string, Names>> Plots::groups(const Names& names) const {
    std::vector<std::pair<std::string, Names>> result;
    for (auto& name : names) {
        auto& r = row(name);
        std::string label = name;
        if ((r.det == 0 || r.det == 1) && (r.side == 0 || r.side == 1)) {
            label = r.det == 0 ? "SFIL" : "Bulk";
            if (type == "layer")
                label += "_y" + std::to_string(r.y);
            else if (type == "module")
                label = r.module;
            label += r.side == 0 ? " xm" : " xp";
        } else if (name.rfind("HODO_", 0) == 0)
            label = "HODO " + name.substr(5, name.find('_', 5) - 5);
        auto i =
            std::find_if(result.begin(), result.end(), [&](auto& g) { return g.first == label; });
        if (i == result.end())
            result.push_back({label, {name}});
        else
            i->second.push_back(name);
    }
    for (auto& g : result)
        if (g.second.size() == 1 && type != "layer")
            g.first = g.second.front();
    return result;
}

// Place z to the right and y upward; paginate channels without coordinates.
void Plots::panels(const std::string& name, const Items& items, const std::string& title,
                   const Names& names, int pageSize) {
    bool spatial = !names.empty();
    int zmin = 100000, zmax = -1, ymin = 100000, ymax = -1, det = -1, side = -1;
    for (auto& n : names) {
        auto& r = row(n);
        if ((r.det != 0 && r.det != 1) || (r.side != 0 && r.side != 1) ||
            (det != -1 && (r.det != det || r.side != side)))
            spatial = false;
        det = r.det;
        side = r.side;
        zmin = std::min(zmin, r.z);
        zmax = std::max(zmax, r.z);
        ymin = std::min(ymin, r.y);
        ymax = std::max(ymax, r.y);
    }
    if (spatial) {
        int nx = zmax - zmin + 1, ny = ymax - ymin + 1;
        std::vector<int> pads;
        std::set<int> occupied;
        for (auto& n : names) {
            auto& r = row(n);
            int pad = (ymax - r.y) * nx + r.z - zmin + 1;
            if (!occupied.insert(pad).second)
                throw std::runtime_error("Multiple channels at the same detector position");
            pads.push_back(pad);
        }
        TCanvas c((name + "_0").c_str(), title.c_str(), std::min(1800, std::max(500, 260 * nx)),
                  std::min(1100, 60 + 200 * ny));
        if (nx * ny > 1)
            c.Divide(nx, ny, .002, .002);
        for (size_t k = 0; k < items.size(); ++k) {
            c.cd(nx * ny > 1 ? pads.at(k) : 0);
            gPad->SetLeftMargin(.12);
            gPad->SetBottomMargin(.12);
            items[k].first->Draw(items[k].second.c_str());
        }
        c.Write();
        return;
    }
    for (size_t page = 0; page < items.size(); page += pageSize) {
        size_t n = std::min(size_t(pageSize), items.size() - page);
        int nx = n > 16 ? 8 : n > 4 ? 4 : n > 1 ? 2 : 1, ny = (n + nx - 1) / nx;
        auto caption = title;
        if (items.size() > size_t(pageSize))
            caption += " · " + std::to_string(page / pageSize + 1) + "/" +
                std::to_string((items.size() + pageSize - 1) / pageSize);
        TCanvas c((name + "_" + std::to_string(page / pageSize)).c_str(), caption.c_str(),
                  std::min(1800, std::max(500, 240 * nx)), std::min(1100, 60 + 210 * ny));
        if (n > 1)
            c.Divide(nx, ny, .002, .002);
        for (size_t k = 0; k < n; ++k) {
            c.cd(n > 1 ? k + 1 : 0);
            gPad->SetLeftMargin(.12);
            gPad->SetBottomMargin(.12);
            items[page + k].first->Draw(items[page + k].second.c_str());
        }
        c.Write();
    }
}

void Plots::drawChannels(const Job& job, size_t number, const std::string& metric) {
    size_t group = 0;
    for (auto& g : groups(job.channels)) {
        Items items;
        for (auto& name : g.second)
            items.push_back({hist(name, metric), metric == "Overlay" ? "COLZ" : "HIST"});
        panels("c_" + std::to_string(number) + "_" + job.executable + "_group" +
                   std::to_string(group++),
               items, g.first + " · " + metric, g.second);
    }
}

std::string Plots::statistics() const {
    return "{\"seen\":" + std::to_string(seen) + ",\"evaluated\":" + std::to_string(evaluated) +
        ",\"passed\":" + std::to_string(passed) + ",\"plotted\":" + std::to_string(plotted) + "}";
}

// Save plot canvases and analysis metadata in one ROOT file.
void Plots::save(const std::string& path, const std::string& analysisJson) {
    TDirectory::TContext context;
    TFile f(path.c_str(), "RECREATE");
    if (f.IsZombie())
        throw std::runtime_error("Cannot create plot file");
    for (size_t i = 0; i < jobs.size(); ++i) {
        auto& j = jobs[i];
        auto metric = metricFor(j, method);
        if (j.executable == "draw_AUX" || j.executable == "DWC")
            draw_aux(*this, j, i);
        else if (j.executable == "draw_heatmap")
            draw_heatmap(*this, j, i);
        else if (metric == "Waveform")
            continue;
        else if (metric == "IntADC")
            draw_int_adc(*this, j, i);
        else if (metric == "PeakADC")
            draw_peak_adc(*this, j, i);
        else if (metric == "Avg")
            draw_avg(*this, j, i);
        else if (metric == "Overlay")
            draw_overlay(*this, j, i);
        else if (metric == "TOA" || metric == "TOT")
            draw_toa_tot(*this, j, i);
        else
            throw std::runtime_error("Unsupported plot: " + metric);
    }
    draw_waveform(*this);
    TNamed("analysis_json", analysisJson.c_str()).Write();
    TNamed("statistics_json", statistics().c_str()).Write();
    if (f.TestBit(TFile::kWriteError))
        throw std::runtime_error("Cannot write plot file");
    f.Close();
}
}
