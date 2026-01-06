


var READTHEDOCS_DATA = {
    "project": "bids-specification",
    "version": "v1.2.1",
    "language": "en",
    "programming_language": "words",
    "page": null,
    "theme": "material",
    "builder": "mkdocs",
    "docroot": "src",
    "source_suffix": ".md",
    "api_host": "https://readthedocs.org",
    "ad_free": true,
    "commit": "b0fbcc120e138f1cea4466192e51faa9551960a5",
    "global_analytics_code": "UA-17997319-1",
    "user_analytics_code": "UA-135334842-1"
}

// Old variables
var doc_version = "v1.2.1";
var doc_slug = "bids\u002Dspecification";
var page_name = "None";
var html_theme = "material";

// mkdocs_page_input_path is only defined on the RTD mkdocs theme but it isn't
// available on all pages (e.g. missing in search result)
if (typeof mkdocs_page_input_path !== "undefined") {
  READTHEDOCS_DATA["page"] = mkdocs_page_input_path.substr(
      0, mkdocs_page_input_path.lastIndexOf(READTHEDOCS_DATA.source_suffix));
}
