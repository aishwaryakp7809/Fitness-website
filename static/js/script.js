document.addEventListener("DOMContentLoaded", () => {
    // Loading effect for forms
    document.querySelectorAll("form").forEach(form => {
        form.addEventListener("submit", () => {
            const btn = form.querySelector("button[type=submit]");
            if (btn) {
                btn.disabled = true;
                const orig = btn.innerText;
                btn.innerText = "Processing...";
                setTimeout(() => {
                    btn.disabled = false;
                    btn.innerText = orig;
                }, 4000);
            }
        });
    });

    // basic hover for cards
    document.querySelectorAll(".card").forEach(card => {
        card.addEventListener("mouseenter", () => {
            card.style.transform = "translateY(-6px)";
            card.style.transition = "all .25s ease";
        });
        card.addEventListener("mouseleave", () => {
            card.style.transform = "translateY(0)";
        });
    });
});
