#pragma once
// Define shared ROOT inputs, selections, and canvas layouts.
#include <boost/property_tree/ptree.hpp>
#include <TCanvas.h>
#include <TFile.h>
#include <TGraph.h>
#include <TH1D.h>
#include <TH2D.h>
#include <TProfile.h>
#include <TNamed.h>
#include <TROOT.h>
#include <TStyle.h>
#include <TTree.h>
#include <algorithm>
#include <cmath>
#include <functional>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <tuple>
#include <vector>

namespace DQMPlot {
using Json = boost::property_tree::ptree;
using Key = std::pair<std::string, std::string>;
using Names = std::vector<std::string>;
using Items = std::vector<std::pair<TObject*, std::string>>;
Json parse(const std::string& text);
std::string encode(const Json& json);

struct Row {
    std::string name, daq, module;
    int det, side, z, y;
};

struct Job {
    std::string executable;
    Names channels;
    bool requiresMatching = false;
};

struct Frame {
    ULong64_t event;
    std::string label;
    Names names;
    std::map<std::string, std::vector<short>> waves;
};

struct Input {
    ULong64_t event = 0, sourceEvent = 0;
    std::string* source = nullptr;
    std::vector<short>*adc = nullptr, *toa = nullptr, *tot = nullptr;
    std::vector<int>* offsets = nullptr;
    std::vector<unsigned char>*present = nullptr, *usable = nullptr;
    std::vector<double>*peak = nullptr, *integral = nullptr, *derived = nullptr;
    TTree* boundTree = nullptr;
    ~Input();
    void bind(TTree& tree);
};

struct Plots {
    Json config, analysis;
    std::vector<Row> rows;
    std::map<std::string, size_t> index;
    std::vector<Job> jobs;
    std::string method, type, revision;
    bool matching;
    long long limit, first;
    ULong64_t seen = 0, evaluated = 0, passed = 0, plotted = 0;
    std::map<Key, std::unique_ptr<TH1>> hists;
    std::map<Key, int> lengths;
    std::set<Key> emptyWaveHists;
    std::map<Key, ULong64_t> channelCounts;
    std::map<std::string, ULong64_t> sourceAccepted;
    std::vector<double> sums;
    std::vector<ULong64_t> counts;
    std::vector<Frame> frames;
    std::string response;
    explicit Plots(const std::string& request);

    const Row& row(const std::string& name) const {
        return rows.at(index.at(name));
    }

    TH1* hist(const std::string& name, const std::string& metric, int samples = 0);
    TH2D* derivedHist(const std::string& name);
    bool passes(const Input& input) const;
    void add(const std::string& path);
    void save(const std::string& path, const std::string& analysisJson);
    std::string statistics() const;
    std::vector<std::pair<std::string, Names>> groups(const Names& names) const;
    void panels(const std::string& name, const Items& items, const std::string& title,
                const Names& names = {}, int pageSize = 33);
    void drawChannels(const Job& job, size_t number, const std::string& metric);
};

std::string metricFor(const Job& job, const std::string& fallback);
std::string histogramName(const Plots&, const std::string&, const std::string&);
TH1* make_peak_adc(const Plots&, const std::string&);
TH1* make_int_adc(const Plots&, const std::string&);
TH1* make_avg(const Plots&, const std::string&, int);
TH1* make_overlay(const Plots&, const std::string&, int);
TH1* make_toa_tot(const Plots&, const std::string&, const std::string&);
void fill_avg(Plots&, const std::string&, const std::vector<short>&);
void fill_overlay(Plots&, const std::string&, const std::vector<short>&);
void fill_toa_tot(Plots&, const std::string&, const std::string&, const std::vector<short>&);
void fill_heatmap(Plots&, size_t, double);
void fill_aux(Plots&, const Job&, const Input&, std::set<std::string>&,
              const std::function<bool(const Key&)>&, bool&);
void draw_peak_adc(Plots&, const Job&, size_t);
void draw_int_adc(Plots&, const Job&, size_t);
void draw_avg(Plots&, const Job&, size_t);
void draw_overlay(Plots&, const Job&, size_t);
void draw_toa_tot(Plots&, const Job&, size_t);
void draw_heatmap(Plots&, const Job&, size_t);
void draw_aux(Plots&, const Job&, size_t);
void draw_waveform(Plots&);
}
