#include "plot_common.h"
#include <limits>
#include <stdexcept>

namespace DQMPlot {
// Read raw waveforms and calculated values from event_tree.
Input::~Input() {
    if (boundTree)
        boundTree->ResetBranchAddresses();
    delete source;
    delete adc;
    delete toa;
    delete tot;
    delete offsets;
    delete present;
    delete usable;
    delete peak;
    delete integral;
    delete derived;
}

void Input::bind(TTree& tree) {
    boundTree = &tree;
    auto bind = [&](const char* name, auto* address) {
        if (!tree.GetBranch(name) || tree.SetBranchAddress(name, address) < 0)
            throw std::runtime_error(std::string("Missing or invalid branch: ") + name);
    };
    bind("event", &event);
    bind("source_event", &sourceEvent);
    bind("source", &source);
    bind("adc", &adc);
    bind("offsets", &offsets);
    bind("present", &present);
    bind("usable", &usable);
    bind("peak", &peak);
    bind("integral", &integral);
    bind("derived", &derived);
    if (tree.GetBranch("toa"))
        bind("toa", &toa);
    if (tree.GetBranch("tot"))
        bind("tot", &tot);
}

// Apply configured cuts to DWC differences, positions, and channel metrics.
bool Plots::passes(const Input& e) const {
    static const std::map<std::string, int> derived = {{"DWC1.x", 0}, {"DWC1.y", 1}, {"DWC2.x", 2},
                                                       {"DWC2.y", 3}, {"HODO.L", 4}, {"HODO.R", 5}};
    for (auto& item : analysis.get_child("cuts")) {
        auto& cut = item.second;
        auto name = cut.get<std::string>("field");
        double value;
        if (name == "DWC.dx" || name == "DWC.dy") {
            int a = name == "DWC.dx" ? 0 : 1;
            value = std::abs(e.derived->at(a) - e.derived->at(a + 2));
        } else if (derived.count(name))
            value = e.derived->at(derived.at(name));
        else {
            auto dot = name.rfind('.');
            auto i = index.at(name.substr(0, dot));
            value = e.usable->at(i) ? (name.substr(dot + 1) == "peak" ? e.peak : e.integral)->at(i)
                                    : std::numeric_limits<double>::quiet_NaN();
        }
        if (!std::isfinite(value))
            return false;
        auto low = cut.get_optional<double>("min"), high = cut.get_optional<double>("max");
        if (low && value < *low)
            return false;
        if (high && (cut.get<bool>("max_exclusive", false) ? value >= *high : value > *high))
            return false;
    }
    return true;
}

static bool sameMapping(const Json& a, const Json& b) {
    if (a.size() != b.size())
        return false;
    auto j = b.begin();
    for (auto& item : a) {
        if (item.second.size() != j->second.size())
            return false;
        for (auto& field : item.second) {
            auto value = j->second.get_optional<std::string>(field.first);
            if (!value || *value != field.second.data())
                return false;
        }
        ++j;
    }
    return true;
}

void Plots::add(const std::string& path) {
    TDirectory::TContext context;
    std::unique_ptr<TFile> f(TFile::Open(path.c_str()));
    if (!f || f->IsZombie())
        throw std::runtime_error("Cannot read committed chunk: " + path);
    auto* metadata = dynamic_cast<TNamed*>(f->Get("mapping_json"));
    if (!metadata || !sameMapping(parse(metadata->GetTitle()), config.get_child("mapping")))
        throw std::runtime_error("Chunk mapping mismatch");
    auto* tree = dynamic_cast<TTree*>(f->Get("event_tree"));
    if (!tree)
        throw std::runtime_error("Missing event_tree");
    for (auto metric : {"TOA", "TOT"})
        if (method == metric || method == "TOA/TOT")
            if (!tree->GetBranch(std::string(metric) == "TOA" ? "toa" : "tot"))
                throw std::runtime_error("Timing data not captured; start a new session");
    Input e;
    e.bind(*tree);
    // Count each event once toward a channel limit shared by plots.
    for (Long64_t k = 0; k < tree->GetEntries(); ++k) {
        if (tree->GetEntry(k) <= 0)
            throw std::runtime_error("Cannot read event_tree entry");
        ++seen;
        ++evaluated;
        if (!passes(e))
            continue;
        std::string source = matching ? "" : *e.source;
        auto accepted = sourceAccepted[source]++;
        ++passed;
        if (method == "Waveform" && accepted < ULong64_t(first))
            continue;
        Frame frame;
        frame.event = e.event;
        frame.label = source.empty() ? "Event " + std::to_string(e.event)
                                     : source + " · Event " + std::to_string(e.sourceEvent);
        bool used = false;
        std::map<Key, bool> decisions;
        std::set<std::tuple<std::string, std::string, bool>> filled;
        std::set<Key> scalarFilled;
        std::set<std::string> auxFilled;
        auto take = [&](const Key& key) {
            auto i = decisions.find(key);
            if (i != decisions.end())
                return i->second;
            bool yes = limit < 0 || channelCounts[key] < ULong64_t(limit);
            if (yes)
                ++channelCounts[key];
            decisions[key] = yes;
            return yes;
        };
        for (auto& job : jobs) {
            auto exe = job.executable;
            if (exe == "DWC" || exe == "draw_AUX") {
                fill_aux(*this, job, e, auxFilled, take, used);
                continue;
            }
            auto metric = metricFor(job, method);
            bool heat = exe == "draw_heatmap", timing = metric == "TOA" || metric == "TOT";
            for (auto& name : job.channels) {
                size_t i = index.at(name);
                Key key{name, metric};
                if (!(timing ? e.present : e.usable)->at(i) || filled.count({name, metric, heat}) ||
                    scalarFilled.count(key) || (metric == "PeakADC" && auxFilled.count(name)))
                    continue;
                int a = e.offsets->at(i), b = e.offsets->at(i + 1);
                if (timing && b - a < 20)
                    continue;
                if (!take(key))
                    continue;
                used = true;
                filled.insert({name, metric, heat});
                if (heat) {
                    fill_heatmap(*this, i, (method == "PeakADC" ? e.peak : e.integral)->at(i));
                    continue;
                }
                if (a < 0 || b < a || size_t(b) > e.adc->size())
                    throw std::runtime_error("Invalid waveform offsets");
                std::vector<short> wave(e.adc->begin() + a, e.adc->begin() + b);
                if (metric == "Waveform") {
                    if (!frame.waves.count(name))
                        frame.names.push_back(name);
                    frame.waves[name] = std::move(wave);
                    continue;
                }
                if (timing) {
                    auto* values = metric == "TOA" ? e.toa : e.tot;
                    if (!values || size_t(b) > values->size() ||
                        std::any_of(values->begin() + a, values->begin() + b,
                                    [](short v) { return v < 0; }))
                        throw std::runtime_error("Timing data not captured; start a new session");
                    fill_toa_tot(*this, name, metric, {values->begin() + a, values->begin() + b});
                } else if (metric == "Avg")
                    fill_avg(*this, name, wave);
                else if (metric == "Overlay")
                    fill_overlay(*this, name, wave);
                else {
                    hist(name, metric)->Fill((metric == "PeakADC" ? e.peak : e.integral)->at(i));
                    scalarFilled.insert(key);
                    if (metric == "PeakADC")
                        auxFilled.insert(name);
                }
            }
        }
        if (used)
            ++plotted;
        if (!frame.names.empty())
            frames.push_back(std::move(frame));
    }
}
}
