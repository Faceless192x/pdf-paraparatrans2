function encodePdfNamePath(value) {
    if (typeof value !== "string") {
        return "";
    }
    return encodeURIComponent(value).replace(/%2F/gi, "/");
}
