#ifndef DQM_MAP_H
#define DQM_MAP_H

#include "../mapping/mapping_CERN2026.h"

#include <TObjArray.h>
#include <TObjString.h>
#include <TRegexp.h>
#include <TString.h>

#include <iostream>
#include <map>
#include <set>
#include <string>
#include <tuple>
#include <vector>

using DQMKey = std::tuple<std::string, int, int>;

inline std::string DQM_CanonicalDAQ(TString d)
{
	d.ToUpper();
	if (d == "BIC")                   return "BIC";
	if (d == "JBNU" || d == "HODO")   return "JBNU";
	if (d == "NKFADC" || d == "FADC") return "NKFADC";
	return "";
}

inline const std::vector<int>& DQM_DAQMIDs(const std::string& daq)
{
	static const std::map<std::string, std::vector<int>> mids = {
		{"BIC", {41, 42, 43}}, {"JBNU", {21}}, {"NKFADC", {1, 2, 3, 4}}};
	static const std::vector<int> none;
	auto it = mids.find(daq);
	return it == mids.end() ? none : it->second;
}

class DQMMapping {
public:
	bool Load()
	{
		fName.clear();
		fKey.clear();
		fOrder.clear();
		fModule.clear();
		for (const auto& e : DQM_MappingTable()) {
			const std::string d = DQM_CanonicalDAQ(e.daq.c_str());
			if (d.empty()) {
				std::cerr << "[DQM] mapping " << e.name << " : unknown DAQ " << e.daq << "\n";
				continue;
			}
			const DQMKey k{d, e.mid, e.ch};
			if (fKey.count(e.name) || fName.count(k)) {
				std::cerr << Form("[DQM] mapping %s (%s MID %d ch %d) : duplicate name or channel, skipped\n",
				                  e.name.c_str(), d.c_str(), e.mid, e.ch);
				continue;
			}
			fKey[e.name] = k;
			fName[k]     = e.name;
			fOrder.push_back(e.name);
			if (e.det >= 0) fModule[e.name.substr(0, e.name.find('_'))].push_back(e.name);
		}
		std::cout << "[DQM] mapping_CERN2026.h : " << fOrder.size() << " named channels\n";
		return !fOrder.empty();
	}

	std::string Name(const DQMKey& k) const
	{
		auto it = fName.find(k);
		return it == fName.end() ? std::string() : it->second;
	}

	std::vector<std::string> Match(TString pattern) const
	{
		pattern.ToUpper();
		const TRegexp re(pattern, kTRUE);
		std::vector<std::string> out;
		for (const auto& n : fOrder) {
			TString u(n.c_str());
			u.ToUpper();
			Ssiz_t len = 0;
			if (u.Index(re, &len) == 0 && len == u.Length()) out.push_back(n);
		}
		return out;
	}

	std::vector<std::string> Exact(const std::string& token) const
	{
		if (fKey.count(token)) return {token};
		auto it = fModule.find(token);
		return it == fModule.end() ? std::vector<std::string>() : it->second;
	}

	const DQMKey& Key(const std::string& name) const { return fKey.at(name); }

private:
	std::map<std::string, DQMKey> fKey;
	std::map<DQMKey, std::string> fName;
	std::vector<std::string>      fOrder;
	std::map<std::string, std::vector<std::string>> fModule;
};

class DQMSelection {
public:

	bool Parse(const char* selector, const DQMMapping& map, bool patterns = false)
	{
		fFiles.clear();
		fChannels.clear();
		fWholeMID.clear();
		fOrder.clear();

		TObjArray* tok = TString(selector).Tokenize(patterns ? " ,;\t" : " \t");
		bool bad = false;
		for (int i = 0; i < tok->GetEntries(); ++i) {
			const TString t = static_cast<TObjString*>(tok->At(i))->String();

			if (!patterns) {
				const auto names = map.Exact(t.Data());
				if (names.empty()) {
					std::cerr << "[DQM] \"" << t << "\" is not a channel or module name in mapping_CERN2026.h"
					          << " (use the exact name, e.g. CC1, DWC1_R, SFIL4_xp_y2, HODO_L_01, SFIL4)\n";
					bad = true;
				}
				for (const auto& n : names) Add(map.Key(n));
				continue;
			}

			const Ssiz_t colon = t.Index(":");
			const std::string daq = DQM_CanonicalDAQ(colon < 0 ? t : TString(t(0, colon)));

			if (!daq.empty()) {
				std::vector<int> mids = DQM_DAQMIDs(daq);
				if (colon >= 0) mids = {TString(t(colon + 1, t.Length())).Atoi()};
				for (int m : mids) {
					fFiles[daq].insert(m);
					fWholeMID.insert({daq, m});
				}
				continue;
			}

			const auto names = map.Match(t);
			if (names.empty()) std::cerr << "[DQM] \"" << t << "\" matches no channel in the mapping\n";
			for (const auto& n : names) Add(map.Key(n));
		}
		delete tok;

		if (bad) {
			fFiles.clear();
			fChannels.clear();
			fOrder.clear();
			return false;
		}
		if (fFiles.empty()) std::cerr << "[DQM] nothing selected by \"" << selector << "\"\n";
		return !fFiles.empty();
	}

	bool Wants(const DQMKey& k) const
	{
		return fWholeMID.count({std::get<0>(k), std::get<1>(k)}) || fChannels.count(k);
	}

	const std::map<std::string, std::set<int>>& Files() const { return fFiles; }

	const std::vector<DQMKey>& Order() const { return fOrder; }

private:
	void Add(const DQMKey& k)
	{
		if (!fChannels.insert(k).second) return;
		fFiles[std::get<0>(k)].insert(std::get<1>(k));
		fOrder.push_back(k);
	}

	std::map<std::string, std::set<int>>   fFiles;
	std::set<DQMKey>                       fChannels;
	std::set<std::pair<std::string, int>>  fWholeMID;
	std::vector<DQMKey>                    fOrder;
};

#endif
