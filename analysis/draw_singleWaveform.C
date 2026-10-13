// 사용법: ./draw_singleWaveform <RunNo> <firstEvt> <nEvt> <channel> [channel ...] [-g]   (nEvt 최대 100, -1 이면 100)

#include "../include/DQMDraw.h"

#include <TH1F.h>
#include <TLegend.h>
#include <TColor.h>

const int kSingleWaveformMaxEvents = 100;

void draw_singleWaveform(int RunNo, const char* channels, long long firstEvt = 0, long long nEvt = -1,
                         const char* inPath = kDQMDefaultPath)
{
	if (nEvt < 0 || nEvt > kSingleWaveformMaxEvents) nEvt = kSingleWaveformMaxEvents;

	DQMMapping map;
	if (!map.Load()) return;
	DQMSelection sel;
	if (!sel.Parse(channels, map)) return;

	std::map<long long, std::map<DQMKey, std::vector<double>>> events;
	std::set<DQMKey> seen;
	DQM_Loop(sel, inPath, RunNo, firstEvt, nEvt,
	         [&](const DQMKey& k, const ChannelWaveform& w, const DAQInfo&, long long evt) {
		events[evt][k] = w.adc;
		seen.insert(k);
	});
	if (events.empty()) {
		std::cerr << "[DQM] nothing to draw for run " << RunNo << "\n";
		return;
	}

	std::vector<DQMKey> order;
	for (const auto& k : sel.Order())
		if (seen.count(k)) order.push_back(k);
	for (const auto& k : seen)
		if (std::find(order.begin(), order.end(), k) == order.end()) order.push_back(k);

	const std::vector<int> colors = {
		TColor::GetColor("#5790fc"), TColor::GetColor("#f89c20"), TColor::GetColor("#e42536"),
		TColor::GetColor("#964a8b"), TColor::GetColor("#9c9ca1"), TColor::GetColor("#7a21dd")};
	if (order.size() > colors.size())
		std::cout << "[DQM] " << order.size() << " channels : colors repeat after " << colors.size() << "\n";

	std::map<DQMKey, size_t> nSamplesOf;
	size_t nSamples = 0;
	for (const auto& e : events)
		for (const auto& w : e.second) {
			nSamplesOf[w.first] = std::max(nSamplesOf[w.first], w.second.size());
			nSamples = std::max(nSamples, w.second.size());
		}

	const TString tag = DQM_FileTag(channels);
	TString gif = DQM_OutputPath("Waveform", RunNo, Form("singleWaveform_%d_%s", RunNo, tag.Data()));
	gif.Replace(gif.Length() - 5, 5, ".gif");
	const TString partial = gSystem->GetDirName(gif) + "/." + gSystem->BaseName(gif);
	gSystem->Unlink(partial);

	TCanvas* c = new TCanvas(Form("c_singleWaveform_%d", RunNo), Form("Run %d single waveform", RunNo), 800, 800);
	c->SetLeftMargin(0.14);
	TH1F* frame = new TH1F(Form("singleWaveform_%d_frame", RunNo), ";sample;ADC", (int)nSamples, 0, (double)nSamples);
	frame->SetDirectory(nullptr);
	frame->SetStats(0);

	std::vector<TH1F*> hists;
	TLegend* leg = new TLegend(0.66, 0.13, 0.88, 0.13 + 0.045 * order.size());
	leg->SetFillStyle(0);
	leg->SetBorderSize(0);
	leg->SetTextFont(42);
	for (size_t i = 0; i < order.size(); ++i) {
		const std::string name = map.Name(order[i]);
		const int ns = (int)nSamplesOf[order[i]];
		TH1F* h = new TH1F(Form("singleWaveform_%d_%s", RunNo, DQM_ChannelId(map, order[i]).Data()), "", ns, 0, ns);
		h->SetDirectory(nullptr);
		h->SetStats(0);
		h->SetLineWidth(2);
		h->SetLineColor(colors[i % colors.size()]);
		hists.push_back(h);
		leg->AddEntry(h, name.empty() ? DQM_ChannelLabel(map, order[i]).Data() : name.c_str(), "l");
	}

	int nFrames = 0;
	for (const auto& e : events) {
		double yMin = 1e300, yMax = -1e300;
		for (size_t i = 0; i < order.size(); ++i) {
			hists[i]->Reset("ICES");
			auto it = e.second.find(order[i]);
			if (it == e.second.end()) continue;
			for (size_t s = 0; s < it->second.size(); ++s) {
				hists[i]->SetBinContent((int)s + 1, it->second[s]);
				yMin = std::min(yMin, it->second[s]);
				yMax = std::max(yMax, it->second[s]);
			}
		}
		const double pad = (yMax > yMin ? yMax - yMin : 1.) * 0.1;
		frame->GetYaxis()->SetRangeUser(yMin - pad, yMax + pad);
		frame->SetTitle(Form("Run %d, Event %lld", RunNo, e.first));

		c->cd();
		frame->Draw();
		for (size_t i = 0; i < order.size(); ++i)
			if (e.second.count(order[i])) hists[i]->Draw("L SAME");
		leg->Draw();
		c->Update();
		++nFrames;
		c->Print(partial + (nFrames == (int)events.size() ? "++" : "+"));
	}
	gSystem->Unlink(gif);
	gSystem->Rename(partial, gif);
	std::cout << Form("[DQM] saved %s (%d events, %lld - %lld)\n", gif.Data(), nFrames,
	                  events.begin()->first, events.rbegin()->first);
}

#ifndef __CLING__
#include "../include/DQMApp.h"
int main(int argc, char** argv)
{
	DQMApp app(argc, argv);
	if (!app.Need(4, "./draw_singleWaveform <RunNo> <firstEvt> <nEvt> <channel> [channel ...] [-g]   (nEvt max 100)"))
		return 1;
	const auto& a = app.Args();
	draw_singleWaveform(std::stoi(a[0]), DQM_JoinArgs(a, 3).c_str(), std::stoll(a[1]), std::stoll(a[2]), DQM_DataPath());
	return app.Run();
}
#endif
