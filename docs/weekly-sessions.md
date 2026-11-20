# Weekly sessions

## Weekly dependency updates

Set up the target plot and repository first. Its contributing guide should describe the eligible dependency changes and their checks. From your Slopmeister checkout, use an unused session name and your repository path.

```sh
bin/slopmeister plot-session /path/to/shop example-app shop-updates-20261116 --weekly-update --tool claude < plots/home/launchd/update-kickoff.md
```

The worker prepares and tests one eligible batch under the plot’s normal permissions. Review its report before ordering publication or deployment. To run a recap manually, omit the update flag and supply the recap kickoff.

```sh
bin/slopmeister plot-session /path/to/shop example-app shop-recap-20261116 < plots/home/launchd/glean-kickoff.md
```

The recap compares the last complete week with its predecessor. Unread sources are labeled in the report. Set up a recurring run with the [optional weekly sessions](home-install.md#optional-weekly-sessions).
