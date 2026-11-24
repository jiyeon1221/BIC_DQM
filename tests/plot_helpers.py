"""Inspect native plotter output through saved ROOT objects."""
from contextlib import contextmanager
from pathlib import Path
from storage.root_writer import root


@contextmanager
def saved_file(plots):
    plots.save()
    config = plots.config
    path = Path(config["plot_dir"]) / config.get("plot_name", f'matched_{config["run"]}.root')
    file = root().TFile.Open(str(path))
    try:
        yield file
    finally:
        file.Close()


def primitives(obj):
    yield obj
    if obj.InheritsFrom("TVirtualPad"):
        for child in obj.GetListOfPrimitives():
            yield from primitives(child)


def objects(file):
    for key in file.GetListOfKeys():
        if key.GetClassName() == "TCanvas":
            yield from primitives(file.Get(key.GetName()))


def histogram(plots, name, metric):
    key = f'h_{name}_{metric}_{plots.analysis["revision"]}'
    with saved_file(plots) as file:
        original = next(obj for obj in objects(file) if obj.GetName() == key)
        clone = original.Clone(key + "_test")
        clone.SetDirectory(0)
        return clone


def waveform_counts(plots, names):
    with saved_file(plots) as file:
        graphs = [str(obj.GetName()) for obj in objects(file) if obj.InheritsFrom("TGraph")]
    return [sum(g.endswith("_" + name) for g in graphs) for name in names]
