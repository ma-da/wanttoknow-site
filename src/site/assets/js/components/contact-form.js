(() => {
  "use strict";

  const form =
    document.querySelector(
      "[data-contact-form]"
    );

  if (!form) return;


  const started =
    form.querySelector(
      "[data-contact-started]"
    );

  const storyUrlWrap =
    form.querySelector(
      "[data-story-url]"
    );

  const storyUrlInput =
    form.querySelector(
      "#contact-url"
    );

  const typeInputs =
    form.querySelectorAll(
      'input[name="contact_type"]'
    );


  /* Record when a human opened the form */

  if (started) {
    started.value =
      String(Date.now());
  }


  /* Show URL only for story submissions */

  function updateStoryUrl() {

    const selected =
      form.querySelector(
        'input[name="contact_type"]:checked'
      )?.value;

    const isStory =
      selected === "story";


    if (storyUrlWrap) {
      storyUrlWrap.hidden =
        !isStory;
    }


    if (storyUrlInput) {

      storyUrlInput.disabled =
        !isStory;

      storyUrlInput.required =
        isStory;

      if (!isStory) {
        storyUrlInput.value =
          "";
      }

    }

  }


  typeInputs.forEach(
    (input) => {

      input.addEventListener(
        "change",
        updateStoryUrl
      );

    }
  );


  updateStoryUrl();
		
		const status =
				form.querySelector(
						"[data-contact-status]"
				);

		const submitButton =
				form.querySelector(
						'button[type="submit"]'
				);


		form.addEventListener(
				"submit",
				async (event) => {

						event.preventDefault();


						if (!form.reportValidity()) {
								return;
						}


						if (submitButton) {
								submitButton.disabled =
										true;
						}


						if (status) {
								status.textContent =
										"Sending…";
						}


						try {

								const response =
										await fetch(
												form.action,
												{
														method: "POST",

														headers: {
																Accept:
																		"application/json"
														},

														body:
																new FormData(form),
												}
										);


								const result =
										await response.json();


								if (!response.ok) {
										throw new Error(
												result.message
												|| "Submission failed."
										);
								}


								if (status) {
										status.textContent =
												result.message
												|| "Thanks. Your message has been received.";
								}


								form.reset();

								/*
										Reset the anti-bot clock for
										another legitimate submission.
								*/

								if (started) {
										started.value =
												String(Date.now());
								}

								updateStoryUrl();


						} catch (error) {

								if (status) {
										status.textContent =
												error.message
												|| (
														"We couldn't send your "
														+ "message. Please try again."
												);
								}


						} finally {

								if (submitButton) {
										submitButton.disabled =
												false;
								}

						}

				}
		);		

})();