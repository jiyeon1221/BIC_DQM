#ifndef DQM_DRAW_H
#define DQM_DRAW_H

#include "DQMMap.h"
#include "DQMSave.h"
#include "reader_BIC.h"
#include "reader_JBNU.h"
#include "reader_NKFADC.h"

#include <TCanvas.h>
#include <TH1.h>
#include <TStyle.h>
#include <TVirtualPad.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <functional>
#include <map>

const char* const kDQMDefaultPath = "/home/kobic/26CERNData/binary";

const unsigned int kDQMTriggerLag = 1000;

const int kDQMPadsPerCanvas = 33;

inline std::unique_ptr<DAQReader> DQM_MakeReader(const std::string& daq)
{
	if (daq == "BIC")    return std::unique_ptr<DAQReader>(new BICReader());
	if (daq == "JBNU")   return std::unique_ptr<DAQReader>(new JBNUReader());
	if (daq == "NKFADC") return std::unique_ptr<DAQReader>(new NKFADCReader());
	std::cerr << "[DQM] unknown DAQ \"" << daq << "\"\n";
	return nullptr;
}

inline void DQM_Loop(const DQMSelection& sel, const char* inPath, int RunNo,
                     long long firstEvt, long long nEvt,
                     const std::function<void(const DQMKey&, const ChannelWaveform&,
                                              const DAQInfo&, long long evt)>& fn)
{
	for (const auto& file : sel.Files()) {
		auto reader = DQM_MakeReader(file.first);
		if (!reader) continue;

		for (int m : file.second) {
			if (!reader->Open(inPath, RunNo, m)) continue;

			std::vector<ChannelWaveform> unit;
			bool haveBase = false;
			unsigned int base = 0;
			long long nWave = 0, minEvt = -1, maxEvt = -1;

			while (reader->Next(unit)) {
				bool pastRange = false;
				for (const auto& w : unit) {
					if (!haveBase) { base = w.trigger; haveBase = true; }
					const long long evt = (long long)w.trigger - base;
					if (evt < firstEvt) continue;
					if (nEvt >= 0 && evt >= firstEvt + nEvt) {
						if (evt >= firstEvt + nEvt + kDQMTriggerLag) pastRange = true;
						continue;
					}
					const DQMKey k{file.first, w.mid, w.ch};
					if (!sel.Wants(k)) continue;
					if (reader->Info().skipAllZero && DAQ_IsAllZero(w.adc)) continue;
					fn(k, w, reader->Info(), evt);
					++nWave;
					if (minEvt < 0 || evt < minEvt) minEvt = evt;
					if (evt > maxEvt) maxEvt = evt;
				}
				if (pastRange) break;
			}
			std::cout << Form("[DQM] %s : %lld channel waveforms, events %lld - %lld, %lld bad units\n",
			                  reader->FileName().Data(), nWave, minEvt, maxEvt, reader->NBad());
			reader->Close();
		}
	}
}

inline TString DQM_ChannelLabel(const DQMMapping& map, const DQMKey& k)
{
	const TString where = Form("%s MID %d ch %d", std::get<0>(k).c_str(), std::get<1>(k), std::get<2>(k));
	const std::string name = map.Name(k);
	return name.empty() ? where : TString(Form("%s (%s)", name.c_str(), where.Data()));
}

inline TString DQM_ChannelId(const DQMMapping& map, const DQMKey& k)
{
	const std::string name = map.Name(k);
	if (!name.empty()) return DQM_FileTag(name.c_str());
	return Form("%s_M%d_C%d", std::get<0>(k).c_str(), std::get<1>(k), std::get<2>(k));
}

template <class H>
std::vector<TCanvas*> DQM_Draw(const std::map<DQMKey, H*>& hists, const DQMSelection& sel, const char* tag,
                               int RunNo, const char* drawOpt, bool logY = false, bool logZ = false,
                               const TString& namedId = "selected")
{
	std::vector<TCanvas*> canvases;
	if (hists.empty()) {
		std::cerr << "[DQM] nothing to draw for run " << RunNo << "\n";
		return canvases;
	}
	gStyle->SetOptStat(1111);
	gStyle->SetTitleSize(0.06f, "t");

	struct Group { TString id, title; std::vector<H*> hists; };
	std::vector<Group> groups;
	std::set<DQMKey> used;

	struct CaloGroup { std::vector<std::pair<std::array<int, 2>, H*>> cells; };
	std::map<std::pair<int, int>, CaloGroup> calo;
	const auto geo = GetSimCaloChMap();
	for (const auto& kv : hists) {
		if (std::get<0>(kv.first) != "BIC") continue;
		const auto g = geo.find({std::get<1>(kv.first), std::get<2>(kv.first)});
		if (g == geo.end()) continue;
		calo[{g->second[0], g->second[1]}].cells.push_back({{g->second[3], g->second[4]}, kv.second});
		used.insert(kv.first);
	}

	std::vector<H*> named;
	for (const auto& k : sel.Order()) {
		if (used.count(k)) continue;
		auto it = hists.find(k);
		if (it == hists.end()) continue;
		named.push_back(it->second);
		used.insert(k);
	}
	if (!named.empty()) groups.push_back({namedId, "selected channels", named});
	for (const auto& kv : hists) {
		if (used.count(kv.first)) continue;
		const TString g = Form("%s MID %d", std::get<0>(kv.first).c_str(), std::get<1>(kv.first));
		if (groups.empty() || groups.back().title != g)
			groups.push_back({Form("%s_M%d", std::get<0>(kv.first).c_str(), std::get<1>(kv.first)), g, {}});
		groups.back().hists.push_back(kv.second);
	}

	const bool oneCanvas = calo.size() == 1 && groups.empty();
	for (const auto& cg : calo) {
		const char* det  = cg.first.first == 0 ? "SFIL" : "Bulk";
		const char* side = cg.first.second == 1 ? "xp" : "xm";
		int zMin = 99, zMax = -1, yMin = 99, yMax = -1;
		for (const auto& cell : cg.second.cells) {
			zMin = std::min(zMin, cell.first[0]); zMax = std::max(zMax, cell.first[0]);
			yMin = std::min(yMin, cell.first[1]); yMax = std::max(yMax, cell.first[1]);
		}
		const int nx = zMax - zMin + 1, ny = yMax - yMin + 1;
		TString cname = Form("c_%s_%d_%s", tag, RunNo, namedId.Data());
		if (!oneCanvas) cname += Form("_%s_%s", det, side);
		TCanvas* c = new TCanvas(cname, Form("Run %d %s : %s %s", RunNo, tag, det, side == TString("xp") ? "+x" : "-x"),
		                         std::min(1800, std::max(500, 260 * nx)), std::min(1100, 60 + 200 * ny));
		if (nx * ny > 1) c->Divide(nx, ny, 0.002, 0.002);
		for (const auto& cell : cg.second.cells) {
			c->cd(nx * ny > 1 ? (yMax - cell.first[1]) * nx + (cell.first[0] - zMin) + 1 : 0);
			if (logY) gPad->SetLogy();
			if (logZ) gPad->SetLogz();
			cell.second->Draw(drawOpt);
		}
		c->Update();
		canvases.push_back(c);
	}

	for (const auto& g : groups) {
		for (size_t first = 0; first < g.hists.size(); first += kDQMPadsPerCanvas) {
			const int n  = (int)std::min<size_t>(kDQMPadsPerCanvas, g.hists.size() - first);
			const int nx = n > 16 ? 8 : (n > 4 ? 4 : (n > 1 ? 2 : 1));
			const int ny = (n + nx - 1) / nx;
			TString cname = Form("c_%s_%d_%s", tag, RunNo, g.id.Data());
			if (first > 0) cname += Form("_%d", (int)(first / kDQMPadsPerCanvas) + 1);
			TCanvas* c = new TCanvas(cname, Form("Run %d %s : %s", RunNo, tag, g.title.Data()),
			                         std::min(1800, std::max(500, 240 * nx)), std::min(1100, 60 + 210 * ny));
			if (n > 1) c->Divide(nx, ny, 0.002, 0.002);
			for (int i = 0; i < n; ++i) {
				c->cd(n > 1 ? i + 1 : 0);
				if (logY) gPad->SetLogy();
				if (logZ) gPad->SetLogz();
				g.hists[first + i]->Draw(drawOpt);
			}
			c->Update();
			canvases.push_back(c);
		}
	}
	return canvases;
}

template <class H>
void DQM_FillAndDraw(int RunNo, const char* channels, long long firstEvt, long long nEvt,
                     const char* inPath, const char* tag, const char* outDir,
                     const char* drawOpt, bool logY, bool logZ,
                     const std::function<H*(const TString& hname, const TString& label,
                                            const ChannelWaveform&, const DAQInfo&)>& make,
                     const std::function<void(H*, const ChannelWaveform&, const DAQInfo&, long long evt)>& fill)
{
	const TString tagCopy(tag);
	tag = tagCopy.Data();

	DQMMapping map;
	if (!map.Load()) return;
	DQMSelection sel;
	if (!sel.Parse(channels, map)) return;

	std::map<DQMKey, H*> hists;
	DQM_Loop(sel, inPath, RunNo, firstEvt, nEvt,
	         [&](const DQMKey& k, const ChannelWaveform& w, const DAQInfo& info, long long evt) {
		H*& h = hists[k];
		if (!h) h = make(Form("%s_%d_%s", tag, RunNo, DQM_ChannelId(map, k).Data()),
		                 DQM_ChannelLabel(map, k), w, info);
		fill(h, w, info, evt);
	});

	for (const auto& k : sel.Order())
		if (!hists.count(k))
			std::cerr << "[DQM] " << DQM_ChannelLabel(map, k) << " : no data (file missing or no event in range)\n";

	const TString fileTag = DQM_FileTag(channels);
	const std::vector<TCanvas*> canvases = DQM_Draw(hists, sel, tag, RunNo, drawOpt, logY, logZ, fileTag);
	if (!canvases.empty())
		DQM_SaveCanvases(canvases, DQM_OutputPath(outDir, RunNo, Form("%s_%d_%s", tag, RunNo, fileTag.Data())));
}

#endif
