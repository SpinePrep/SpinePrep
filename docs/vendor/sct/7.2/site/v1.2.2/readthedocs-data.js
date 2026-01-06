


var READTHEDOCS_DATA = {
    "project": "bids-specification",
    "version": "v1.2.2",
    "language": "en",
    "programming_language": "words",
    "page": null,
    "theme": "material",
    "builder": "mkdocs",
    "docroot": "src",
    "source_suffix": ".md",
    "api_host": "https://readthedocs.org",
    "proxied_api_host": "https://readthedocs.org",
    "ad_free": true,
    "commit": "3d55770c21ac5cc9015c93adb9bc145d0318bfa1",
    "global_analytics_code": "UA-17997319-1",
    "user_analytics_code": "UA-135334842-1"
}

// Old variables
var doc_version = "v1.2.2";
var doc_slug = "bids\u002Dspecification";
var page_name = "None";
var html_theme = "material";

// mkdocs_page_input_path is only defined on the RTD mkdocs theme but it isn't
// available on all pages (e.g. missing in search result)
if (typeof mkdocs_page_input_path !== "undefined") {
  READTHEDOCS_DATA["page"] = mkdocs_page_input_path.substr(
      0, mkdocs_page_input_path.lastIndexOf(READTHEDOCS_DATA.source_suffix));
}
