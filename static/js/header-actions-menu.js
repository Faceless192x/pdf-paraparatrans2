(function () {
    function $(id) {
        return document.getElementById(id);
    }

    const root = $('headerActionsMenu');
    const toggle = $('headerActionsMenuToggle');
    const panel = $('headerActionsMenuPanel');

    function isReady() {
        return !!(root && toggle && panel);
    }

    function setOpen(open) {
        if (!isReady()) return;
        root.classList.toggle('is-open', open);
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function isOpen() {
        return isReady() && root.classList.contains('is-open');
    }

    function open() {
        setOpen(true);
    }

    function close() {
        setOpen(false);
    }

    function toggleOpen() {
        setOpen(!isOpen());
    }

    // Expose for inline onclick close calls
    window.HeaderActionsMenu = {
        open,
        close,
        toggle: toggleOpen,
    };

    document.addEventListener('DOMContentLoaded', function () {
        if (!isReady()) return;

        toggle.addEventListener('click', function (e) {
            e.preventDefault();
            toggleOpen();
        });

        // Escape to close
        document.addEventListener('keydown', function (e) {
            if (!isOpen()) return;
            if (e.key === 'Escape') {
                close();
                toggle.focus();
            }
        });
    });
})();
