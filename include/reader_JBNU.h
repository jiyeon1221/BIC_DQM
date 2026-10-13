#ifndef READER_JBNU_H
#define READER_JBNU_H

#include "DAQReader.h"

class JBNUReader : public PacketReader {
public:
	const DAQInfo& Info() const override
	{
		static const DAQInfo info{"JBNU", {21},
		                          +1, 0, 0, 240, false, false,
		                          120, {1200, -200, 1000}, {0, -200, 1200},
		                          {10000, 0, 20000}, {1000, -100, 150000},
		                          -32768, 32767};
		return info;
	}
	bool Open(const char* inPath, int RunNo, int mid) override
	{
		return OpenFile(Form("%s/Run_%05d_JBNU_%d.dat", inPath, RunNo, mid), mid);
	}

protected:
	int SampleStride() const override { return 2; }
};

#endif
